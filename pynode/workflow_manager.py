"""WorkflowManager: owns all mutable per-application workflow state.

One instance is attached to each Flask app (see ``pynode.server.create_app``)
under ``app.extensions['workflow_manager']``. It owns:

- the workflow metadata dict and the working/deployed engine pairs,
- the active workflow id and the reentrant state lock guarding them,
- persistence paths and save/load (atomic save, bounded backups, v1
  migration),
- the SSE debug broadcast worker and its per-client message queues.

Static, process-wide node-type data (registries, node-types cache) lives in
``pynode.node_registry``.
"""

import json
import logging
import os
import queue
import shutil
import threading
import time
from datetime import datetime

from pynode import config, node_registry
from pynode.config import PKG_DIR  # noqa: F401 (re-exported, used by server.py)

logger = logging.getLogger(__name__)

# Base directory for project root (kept as a BC re-export; new code should
# use pynode.config.resolve_data_dir(), which falls back to ~/.pynode when
# this location is not a source checkout).
BASE_DIR = config.CHECKOUT_DIR

# Maximum number of timestamped backups kept in workflows/_backups.
# Older backups are pruned on every save.
MAX_BACKUPS = 20


class WorkflowManager:
    """All mutable workflow state for one application instance."""

    def __init__(self, workflows_dir=None, workflow_file=None,
                 upload_base_dir=None, max_backups=MAX_BACKUPS):
        # Multi-workflow state
        # Each workflow has its own working + deployed engine pair
        self.workflows = {}          # workflow_id -> { 'name': str, 'enabled': bool }
        self.working_engines = {}    # workflow_id -> WorkflowEngine
        self.deployed_engines = {}   # workflow_id -> WorkflowEngine
        self.active_workflow_id = None

        # Reentrant lock guarding all mutations/iterations of the workflow
        # state dicts above (workflows, working_engines, deployed_engines) and
        # active_workflow_id. Reentrant so helpers that already hold it
        # (e.g. create_new_workflow) can be called from routes that also
        # acquire it.
        self.state_lock = threading.RLock()

        # Workflow persistence directories and files. Default resolution
        # (source checkout vs PYNODE_DATA_DIR vs ~/.pynode) lives in
        # pynode.config.
        self.workflows_dir = workflows_dir or config.resolve_workflows_dir()
        self.workflow_file = workflow_file or os.path.join(self.workflows_dir, 'workflow.json')
        self.max_backups = max_backups

        # File upload base directory (see pynode.api.uploads for the
        # allowlisted subdirectories).
        self.upload_base_dir = upload_base_dir or PKG_DIR

        # Ensure workflows directory exists
        os.makedirs(self.workflows_dir, exist_ok=True)

        # SSE debug broadcast state (per-app so no cross-app leakage)
        # Queue for debug messages (for SSE): client_id -> queue.Queue
        self.debug_message_queues = {}
        # Lock guarding registration/removal of SSE client queues
        self.clients_lock = threading.Lock()
        self._debug_broadcast_thread = None
        self._debug_broadcast_running = False
        self._debug_broadcast_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Engine / workflow helpers
    # ------------------------------------------------------------------

    def create_workflow_engine(self):
        """Create a new WorkflowEngine with all node types registered."""
        return node_registry.create_workflow_engine()

    def get_working_engine(self, workflow_id=None):
        """Get working engine for a workflow, defaulting to active."""
        with self.state_lock:
            wid = workflow_id or self.active_workflow_id
            return self.working_engines.get(wid)

    def get_deployed_engine(self, workflow_id=None):
        """Get deployed engine for a workflow, defaulting to active."""
        with self.state_lock:
            wid = workflow_id or self.active_workflow_id
            return self.deployed_engines.get(wid)

    def find_deployed_node(self, node_id):
        """Find a node across all deployed engines. Returns (node, workflow_id) or (None, None)."""
        with self.state_lock:
            engines = list(self.deployed_engines.items())
        for wid, engine in engines:
            node = engine.get_node(node_id)
            if node:
                return node, wid
        return None, None

    def unique_workflow_name(self, desired_name, exclude_id=None):
        """Ensure unique workflow name, appending (n) if needed."""
        existing = {w['name'] for wid, w in self.workflows.items() if wid != exclude_id}
        if desired_name not in existing:
            return desired_name
        n = 1
        while f"{desired_name} ({n})" in existing:
            n += 1
        return f"{desired_name} ({n})"

    def create_new_workflow(self, name=None, workflow_id=None, enabled=True):
        """Create a new workflow with working and deployed engines."""
        with self.state_lock:
            if workflow_id is None:
                # Millisecond timestamps alone can collide when two workflows are
                # created within the same millisecond (the second would silently
                # overwrite the first); append a counter until the id is unique.
                base_id = f"wf_{int(time.time() * 1000)}"
                workflow_id = base_id
                suffix = 1
                while workflow_id in self.workflows:
                    workflow_id = f"{base_id}_{suffix}"
                    suffix += 1
            if name is None:
                name = "New Workflow"
            name = self.unique_workflow_name(name)

            self.workflows[workflow_id] = {'name': name, 'enabled': enabled}
            self.working_engines[workflow_id] = self.create_workflow_engine()
            self.deployed_engines[workflow_id] = self.create_workflow_engine()
            self.working_engines[workflow_id].workflow_id = workflow_id
            self.deployed_engines[workflow_id].workflow_id = workflow_id

            if self.active_workflow_id is None:
                self.active_workflow_id = workflow_id

            return workflow_id

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _prune_backups(self, backup_dir):
        """Delete oldest backups so at most max_backups remain.

        Backup filenames embed a timestamp (workflow_YYYYMMDD_HHMMSS.json), so a
        lexical sort orders them chronologically.
        """
        try:
            backups = sorted(
                f for f in os.listdir(backup_dir)
                if f.startswith('workflow_') and f.endswith('.json')
            )
            for stale in backups[:-self.max_backups]:
                try:
                    os.remove(os.path.join(backup_dir, stale))
                except OSError as e:
                    logger.warning(f"Failed to prune backup {stale}: {e}")
        except OSError as e:
            logger.warning(f"Failed to prune backups in {backup_dir}: {e}")

    def save_workflow_to_disk(self):
        """Save all workflows to disk atomically, with bounded backups."""
        try:
            # Backup existing workflow if it exists
            if os.path.exists(self.workflow_file):
                try:
                    backup_dir = os.path.join(self.workflows_dir, '_backups')
                    os.makedirs(backup_dir, exist_ok=True)

                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    backup_file = os.path.join(backup_dir, f'workflow_{timestamp}.json')
                    shutil.copy2(self.workflow_file, backup_file)
                    logger.info(f"Backed up workflow to {backup_file}")
                    self._prune_backups(backup_dir)
                except (PermissionError, OSError) as e:
                    logger.warning(f"Failed to create backup: {e}")

            # Build multi-workflow save data
            workflows_data = []
            with self.state_lock:
                active_workflow = self.active_workflow_id
                for wid, meta in self.workflows.items():
                    engine = self.working_engines.get(wid)
                    if engine:
                        wf_export = engine.export_workflow()
                        workflows_data.append({
                            'id': wid,
                            'name': meta['name'],
                            'enabled': meta['enabled'],
                            'nodes': wf_export.get('nodes', []),
                            'connections': wf_export.get('connections', [])
                        })

            save_data = {
                'version': 2,
                'activeWorkflow': active_workflow,
                'workflows': workflows_data
            }

            # Atomic write: dump to a temp file in the same directory, then
            # os.replace() over the target so a crash mid-write can't corrupt it.
            tmp_file = self.workflow_file + '.tmp'
            with open(tmp_file, 'w') as f:
                json.dump(save_data, f, indent=2)
            os.replace(tmp_file, self.workflow_file)
            logger.info(f"Saved {len(workflows_data)} workflow(s) to {self.workflow_file}")

        except PermissionError:
            logger.error(f"Permission denied when saving to {self.workflow_file}")
            logger.error("Please run the following command in terminal to fix ownership:")
            logger.error(f"  sudo chown -R $USER:$USER {self.workflows_dir}")
        except Exception as e:
            logger.error(f"Failed to save workflow: {e}")

    def load_workflow_from_disk(self):
        """Load workflows from disk if file exists. Auto-migrates v1 format."""
        try:
            if os.path.exists(self.workflow_file):
                with open(self.workflow_file, 'r') as f:
                    data = json.load(f)

                # Detect and migrate v1 format (single workflow with nodes/connections at top level)
                if 'workflows' not in data:
                    data = {
                        'version': 2,
                        'activeWorkflow': 'workflow_1',
                        'workflows': [{
                            'id': 'workflow_1',
                            'name': 'Workflow 1',
                            'enabled': True,
                            'nodes': data.get('nodes', []),
                            'connections': data.get('connections', [])
                        }]
                    }
                    logger.info("Migrated v1 workflow format to v2 multi-workflow format")

                # Load each workflow
                with self.state_lock:
                    for wf in data.get('workflows', []):
                        wid = wf['id']
                        self.workflows[wid] = {
                            'name': wf.get('name', 'Unnamed'),
                            'enabled': wf.get('enabled', True)
                        }
                        self.working_engines[wid] = self.create_workflow_engine()
                        self.deployed_engines[wid] = self.create_workflow_engine()
                        self.working_engines[wid].workflow_id = wid
                        self.deployed_engines[wid].workflow_id = wid

                        wf_data = {
                            'nodes': wf.get('nodes', []),
                            'connections': wf.get('connections', [])
                        }

                        # Import into both engines
                        self.deployed_engines[wid].import_workflow(wf_data)
                        if self.workflows[wid]['enabled']:
                            self.deployed_engines[wid].start()
                        self.working_engines[wid].import_workflow(wf_data)

                    self.active_workflow_id = data.get('activeWorkflow')
                    # Ensure active workflow exists
                    if self.active_workflow_id not in self.workflows and self.workflows:
                        self.active_workflow_id = next(iter(self.workflows))

                    total_nodes = sum(len(e.nodes) for e in self.working_engines.values())
                logger.info(f"Loaded {len(self.workflows)} workflow(s), {total_nodes} total nodes")
            else:
                # No workflow file - create default workflow
                self.create_new_workflow(name='Workflow 1', workflow_id='workflow_1')
                self.deployed_engines['workflow_1'].start()
                logger.info("No workflow file found, starting with empty workflow")
        except Exception as e:
            logger.error(f"Failed to load workflow: {e} (type: {type(e).__name__})")
            logger.debug("Full traceback:", exc_info=True)
            # On error, ensure at least one workflow exists
            if not self.workflows:
                self.create_new_workflow(name='Workflow 1', workflow_id='workflow_1')
            try:
                for engine in self.deployed_engines.values():
                    if not engine.running:
                        engine.start()
            except Exception as start_error:
                logger.error(f"Failed to start deployed engine during recovery: {start_error}")

    # ------------------------------------------------------------------
    # SSE debug broadcast
    # ------------------------------------------------------------------

    def start_debug_broadcast(self):
        """Start a single background thread that polls nodes and broadcasts to all clients.

        The thread is a daemon by design: it dies with the process, so no atexit
        hook is needed. Use stop_debug_broadcast() for an explicit shutdown.
        """
        with self._debug_broadcast_lock:
            if self._debug_broadcast_running:
                return

            self._debug_broadcast_running = True
            self._debug_broadcast_thread = threading.Thread(
                target=self._debug_broadcast_worker, daemon=True)
            self._debug_broadcast_thread.start()

    def stop_debug_broadcast(self):
        """Stop the debug broadcast worker thread (best-effort, brief join)."""
        with self._debug_broadcast_lock:
            self._debug_broadcast_running = False
            thread = self._debug_broadcast_thread
            self._debug_broadcast_thread = None

        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _debug_broadcast_worker(self):
        """Background worker that polls nodes and broadcasts to all connected clients.
        Uses the SSE handler registry to dynamically discover what to broadcast."""
        last_throttle_update = {}  # handler_key -> last_update_time

        while self._debug_broadcast_running:
            try:
                # Only poll if there are connected clients
                if not self.debug_message_queues:
                    time.sleep(0.1)
                    continue

                current_time = time.time()
                messages_sent = False

                # Iterate all deployed engines
                for wid, engine in list(self.deployed_engines.items()):
                    if not engine.running:
                        continue

                    # Get errors from system error node
                    all_errors = engine.get_system_errors()
                    if all_errors:
                        data = {'type': 'errors', 'data': all_errors, 'workflowId': wid}
                        self._broadcast_to_all_clients(data)
                        engine.clear_system_errors()
                        messages_sent = True

                    # Poll all nodes that have registered SSE handlers
                    for node_id, node in engine.nodes.items():
                        if node.type not in node_registry.sse_handler_registry:
                            continue

                        for handler_def in node_registry.sse_handler_registry[node.type]:
                            event_type = handler_def['type']
                            handler_name = handler_def['handler']
                            throttle = handler_def.get('throttle')

                            # Check throttle
                            if throttle is not None:
                                handler_key = f"{node_id}_{event_type}"
                                last_update = last_throttle_update.get(handler_key, 0)
                                if current_time - last_update < throttle:
                                    continue
                                last_throttle_update[handler_key] = current_time

                            handler = getattr(node, handler_name, None)
                            if handler is None or not callable(handler):
                                continue

                            try:
                                result = handler()
                                if result is None:
                                    continue

                                # Special handling for 'messages' type: wrap in data key
                                if event_type == 'messages':
                                    data = {'type': 'messages', 'data': result, 'workflowId': wid}
                                else:
                                    data = {
                                        'type': event_type,
                                        'nodeId': node_id,
                                        'workflowId': wid,
                                    }
                                    # If result is a dict, merge it into data
                                    if isinstance(result, dict):
                                        data.update(result)
                                    else:
                                        data['data'] = result

                                self._broadcast_to_all_clients(data)
                                messages_sent = True
                            except Exception as e:
                                logger.warning(f"SSE handler error ({node.type}.{handler_name}): {e}")

                # Adaptive sleep
                if messages_sent:
                    time.sleep(0.01)
                else:
                    time.sleep(0.05)

            except Exception as e:
                logger.error(f"Debug broadcast error: {e}")
                time.sleep(0.1)

    def _broadcast_to_all_clients(self, data):
        """Send data to all connected SSE clients."""
        dead_clients = []
        for client_id, q in list(self.debug_message_queues.items()):
            try:
                q.put_nowait(data)
            except queue.Full:
                # Client queue is full, skip
                pass
            except Exception:
                dead_clients.append(client_id)

        # Clean up dead clients
        if dead_clients:
            with self.clients_lock:
                for client_id in dead_clients:
                    self.debug_message_queues.pop(client_id, None)

    # ------------------------------------------------------------------
    # Shutdown (used by tests to guarantee no leaked threads)
    # ------------------------------------------------------------------

    def shutdown(self):
        """Stop the broadcast worker and every deployed engine this manager owns."""
        self.stop_debug_broadcast()
        with self.state_lock:
            engines = list(self.deployed_engines.values())
        for engine in engines:
            try:
                if engine.running:
                    engine.stop()
            except Exception:
                pass
