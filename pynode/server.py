"""
Flask REST API for the Node-RED-like system.
Provides endpoints for managing nodes, connections, and workflows.
"""

from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import os
import json
import time
import queue
import threading
import shutil
import logging
from datetime import datetime

from pynode.workflow_engine import WorkflowEngine
from pynode import nodes

logger = logging.getLogger(__name__)

# Set the base directory for project root (for workflow.json)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Package directory (for static files)
PKG_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder=os.path.join(PKG_DIR, 'static'), static_url_path='')
CORS(app)  # Enable CORS for frontend


# ------------------------------------------------------------------
# JSON error envelopes: API clients always get JSON, never Flask's HTML
# error pages. Error contract: {'success': False, 'error': str}.
# ------------------------------------------------------------------

def _json_error(message, status):
    return jsonify({'success': False, 'error': message}), status


@app.errorhandler(400)
def _handle_400(e):
    return _json_error(getattr(e, 'description', None) or 'Bad request', 400)


@app.errorhandler(404)
def _handle_404(e):
    return _json_error('Not found', 404)


@app.errorhandler(405)
def _handle_405(e):
    return _json_error('Method not allowed', 405)


@app.errorhandler(500)
def _handle_500(e):
    return _json_error('Internal server error', 500)


def _get_json_body(required=True):
    """Parse the request body as a JSON object.

    Returns a dict on success. Returns None when the body is invalid: not
    parseable JSON, not a JSON object, or missing while ``required`` is True.
    A missing/empty body with ``required=False`` yields ``{}``.
    """
    data = request.get_json(silent=True)
    if data is None:
        # get_json(silent=True) is None for both "no body" and "bad JSON";
        # treat any non-empty unparseable body as invalid even when optional.
        if required or request.get_data(cache=True):
            return None
        return {}
    if not isinstance(data, dict):
        return None
    return data


_INVALID_BODY_ERROR = 'Invalid or missing JSON body'

# Multi-workflow state
# Each workflow has its own working + deployed engine pair
_workflows = {}          # workflow_id -> { 'name': str, 'enabled': bool }
_working_engines = {}    # workflow_id -> WorkflowEngine
_deployed_engines = {}   # workflow_id -> WorkflowEngine
_active_workflow_id = None

# Reentrant lock guarding all mutations/iterations of the workflow state dicts
# above (_workflows, _working_engines, _deployed_engines) and _active_workflow_id.
# Reentrant so helpers that already hold it (e.g. _create_new_workflow) can be
# called from routes that also acquire it.
_state_lock = threading.RLock()

# Workflow persistence directories and files
WORKFLOWS_DIR = os.path.join(BASE_DIR, 'workflows')
WORKFLOW_FILE = os.path.join(WORKFLOWS_DIR, 'workflow.json')

# Maximum number of timestamped backups kept in workflows/_backups.
# Older backups are pruned on every save.
MAX_BACKUPS = 20

# File upload configuration: uploads may only land in these subdirectories
# of UPLOAD_BASE_DIR (the package directory). Anything else is rejected.
UPLOAD_BASE_DIR = PKG_DIR
ALLOWED_UPLOAD_SUBDIRS = ('models', 'uploads')

# Ensure workflows directory exists
os.makedirs(WORKFLOWS_DIR, exist_ok=True)

# Reference engine for node type introspection only
_reference_engine = WorkflowEngine()
for node_class in nodes.get_all_node_types():
    _reference_engine.register_node_type(node_class)


def _create_workflow_engine():
    """Create a new WorkflowEngine with all node types registered."""
    engine = WorkflowEngine()
    for node_class in nodes.get_all_node_types():
        engine.register_node_type(node_class)
    return engine


def _get_workflow_id_from_request():
    """Extract workflow_id from request query params, defaulting to active."""
    with _state_lock:
        return request.args.get('workflow', _active_workflow_id)


def _get_working_engine(workflow_id=None):
    """Get working engine for a workflow, defaulting to active."""
    with _state_lock:
        wid = workflow_id or _active_workflow_id
        return _working_engines.get(wid)


def _get_deployed_engine(workflow_id=None):
    """Get deployed engine for a workflow, defaulting to active."""
    with _state_lock:
        wid = workflow_id or _active_workflow_id
        return _deployed_engines.get(wid)


def _find_deployed_node(node_id):
    """Find a node across all deployed engines. Returns (node, workflow_id) or (None, None)."""
    with _state_lock:
        engines = list(_deployed_engines.items())
    for wid, engine in engines:
        node = engine.get_node(node_id)
        if node:
            return node, wid
    return None, None


def _unique_workflow_name(desired_name, exclude_id=None):
    """Ensure unique workflow name, appending (n) if needed."""
    existing = {w['name'] for wid, w in _workflows.items() if wid != exclude_id}
    if desired_name not in existing:
        return desired_name
    n = 1
    while f"{desired_name} ({n})" in existing:
        n += 1
    return f"{desired_name} ({n})"


def _create_new_workflow(name=None, workflow_id=None, enabled=True):
    """Create a new workflow with working and deployed engines."""
    global _active_workflow_id
    with _state_lock:
        if workflow_id is None:
            # Millisecond timestamps alone can collide when two workflows are
            # created within the same millisecond (the second would silently
            # overwrite the first); append a counter until the id is unique.
            base_id = f"wf_{int(time.time() * 1000)}"
            workflow_id = base_id
            suffix = 1
            while workflow_id in _workflows:
                workflow_id = f"{base_id}_{suffix}"
                suffix += 1
        if name is None:
            name = "New Workflow"
        name = _unique_workflow_name(name)

        _workflows[workflow_id] = {'name': name, 'enabled': enabled}
        _working_engines[workflow_id] = _create_workflow_engine()
        _deployed_engines[workflow_id] = _create_workflow_engine()

        if _active_workflow_id is None:
            _active_workflow_id = workflow_id

        return workflow_id

# Cache for node types (built once at startup or on first request)
_node_types_cache = None

def _build_node_types_cache():
    """Build the node types cache from registered node types."""
    global _node_types_cache
    
    from pynode.nodes.base_node import BaseNode
    base_properties = getattr(BaseNode, 'properties', [])
    
    # Define category ordering
    category_order = [
        'common',
        'node probes',
        'logic',
        'function',
        'input',
        'output',
        'vision',
        'analysis',        
        'network',
        'OpenCV'
    ]
    
    node_types = []
    for name, node_class in _reference_engine.node_types.items():
        # Skip ErrorNode - it's a system node that shouldn't be manually added
        if node_class.hidden:
            continue
            
        display_name = getattr(node_class, 'display_name', name)
        icon = getattr(node_class, 'icon', '◆')
        category = getattr(node_class, 'category', 'custom')
        color = getattr(node_class, 'color', '#2d2d30')
        border_color = getattr(node_class, 'border_color', '#555')
        text_color = getattr(node_class, 'text_color', '#d4d4d4')
        input_count = getattr(node_class, 'input_count', 1)
        output_count = getattr(node_class, 'output_count', 1)
        
        # Handle callable properties (get_properties classmethod)
        if hasattr(node_class, 'get_properties') and callable(node_class.get_properties):
            node_properties = node_class.get_properties()
        else:
            node_properties = getattr(node_class, 'properties', [])
        
        # Ensure node_properties is iterable (list or tuple)
        if not isinstance(node_properties, (list, tuple)):
            node_properties = []
        
        # Get property names from node-specific properties to avoid duplicates
        node_prop_names = {prop.get('name') for prop in node_properties if isinstance(prop, dict)}
        
        # Add base properties that aren't overridden by node-specific properties
        merged_properties = [prop for prop in base_properties if prop.get('name') not in node_prop_names]
        # Add all node-specific properties
        merged_properties.extend(node_properties)
        
        ui_component = getattr(node_class, 'ui_component', None)
        ui_component_config = getattr(node_class, 'ui_component_config', {})
        info = getattr(node_class, 'info', '')
        
        node_types.append({
            'type': name,
            'name': display_name,
            'icon': icon,
            'category': category,
            'color': color,
            'borderColor': border_color,
            'textColor': text_color,
            'inputCount': input_count,
            'outputCount': output_count,
            'properties': merged_properties,
            'uiComponent': ui_component,
            'uiComponentConfig': ui_component_config,
            'info': info
        })
    
    # Sort node types by category order, then by name within each category
    def get_category_sort_key(node_type):
        category = node_type['category']
        try:
            # Categories in the order list get their index
            order_index = category_order.index(category)
        except ValueError:
            # Categories not in the list go to the end (third party)
            order_index = len(category_order)
        return (order_index, node_type['name'])
    
    node_types.sort(key=get_category_sort_key)
    
    _node_types_cache = node_types
    return _node_types_cache

# Build cache at startup
_build_node_types_cache()

# ==============================================================================
# Dynamic Node Endpoint and SSE Registration
# ==============================================================================

# Build a registry of node types that have SSE handlers
# Maps node_type_name -> list of sse_handler defs
_sse_handler_registry = {}

# Build a registry of node types that have api_routes
# Maps node_type_name -> list of route defs  
_api_route_registry = {}

def _build_node_registries():
    """Scan all node classes and build registries for API routes and SSE handlers."""
    for node_class in nodes.get_all_node_types():
        node_type_name = node_class.__name__
        
        api_routes = getattr(node_class, 'api_routes', [])
        if api_routes:
            _api_route_registry[node_type_name] = api_routes
        
        sse_handlers = getattr(node_class, 'sse_handlers', [])
        if sse_handlers:
            _sse_handler_registry[node_type_name] = sse_handlers

_build_node_registries()


def _register_dynamic_node_routes():
    """Register Flask routes for all node types that declare api_routes."""
    registered = set()
    
    for node_type_name, routes in _api_route_registry.items():
        for route_def in routes:
            route = route_def['route']
            methods = route_def.get('methods', ['GET'])
            handler_name = route_def['handler']
            route_type = route_def.get('type', 'json')
            
            # Create a unique endpoint name for Flask
            # Combine methods to handle same route with different methods
            methods_key = '_'.join(sorted(methods))
            endpoint_name = f"node_{node_type_name}_{route}_{methods_key}"
            
            if endpoint_name in registered:
                continue
            registered.add(endpoint_name)
            
            if route_type == 'file_upload':
                allowed_ext = route_def.get('allowed_extensions', set())
                _register_file_upload_route(route, methods, handler_name, endpoint_name, allowed_ext)
            elif route_type == 'stream':
                _register_stream_route(route, handler_name, endpoint_name)
            else:
                _register_json_route(route, methods, handler_name, endpoint_name)


def _resolve_node_handler(node_id, handler_name):
    """Resolve a deployed node and one of its callable handler methods.

    Returns (node, method, error_response). On success error_response is None;
    on failure node/method are None and error_response is a (json, status) tuple.
    """
    node, _ = _find_deployed_node(node_id)
    if not node:
        return None, None, (jsonify({'success': False, 'error': 'Node not found'}), 404)

    method = getattr(node, handler_name, None)
    if method is None or not callable(method):
        return None, None, (jsonify({'success': False, 'error': f'Node does not support {handler_name}'}), 400)

    return node, method, None


def _add_node_route(route, view_func, endpoint_name, methods):
    """Register a Flask URL rule under the standard node API prefix."""
    app.add_url_rule(
        f'/api/nodes/<node_id>/{route}',
        endpoint=endpoint_name,
        view_func=view_func,
        methods=methods
    )


def _register_json_route(route, methods, handler_name, endpoint_name):
    """Register a standard JSON API route."""
    def handler(node_id):
        _, method, error = _resolve_node_handler(node_id, handler_name)
        if error:
            return error
        try:
            result = method()
            if result is None:
                return '', 204
            return jsonify(result)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    _add_node_route(route, handler, endpoint_name, methods)


def _register_file_upload_route(route, methods, handler_name, endpoint_name, allowed_extensions):
    """Register a file upload API route."""
    def handler(node_id):
        _, method, error = _resolve_node_handler(node_id, handler_name)
        if error:
            # Re-shape error payload to the success/error contract used by uploads
            payload, status = error
            return jsonify({'success': False, 'error': payload.get_json()['error']}), status

        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        if not file.filename or file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        if allowed_extensions:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in allowed_extensions:
                return jsonify({'success': False, 'error': f'Unsupported file type: {ext}'}), 400

        try:
            file_bytes = file.read()
            result = method(file_bytes, file.filename)
            return jsonify(result)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    _add_node_route(route, handler, endpoint_name, methods)


def _register_stream_route(route, handler_name, endpoint_name):
    """Register an MJPEG stream route."""
    def handler(node_id):
        _, method, error = _resolve_node_handler(node_id, handler_name)
        if error:
            return error

        def generate():
            for img_data in method():
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + img_data + b'\r\n')

        return Response(
            stream_with_context(generate()),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )

    _add_node_route(route, handler, endpoint_name, ['GET'])


# Register all dynamic routes at startup (before app.run)
_register_dynamic_node_routes()

# Queue for debug messages (for SSE)
debug_message_queues = {}
# Lock guarding registration/removal of SSE client queues in debug_message_queues
_clients_lock = threading.Lock()
debug_broadcast_thread = None
debug_broadcast_running = False
debug_broadcast_lock = threading.Lock()

def start_debug_broadcast():
    """Start a single background thread that polls nodes and broadcasts to all clients.

    The thread is a daemon by design: it dies with the process, so no atexit
    hook is needed. Use stop_debug_broadcast() for an explicit shutdown.
    """
    global debug_broadcast_thread, debug_broadcast_running

    with debug_broadcast_lock:
        if debug_broadcast_running:
            return

        debug_broadcast_running = True
        debug_broadcast_thread = threading.Thread(target=_debug_broadcast_worker, daemon=True)
        debug_broadcast_thread.start()


def stop_debug_broadcast():
    """Stop the debug broadcast worker thread (best-effort, brief join)."""
    global debug_broadcast_thread, debug_broadcast_running

    with debug_broadcast_lock:
        debug_broadcast_running = False
        thread = debug_broadcast_thread
        debug_broadcast_thread = None

    if thread is not None and thread.is_alive():
        thread.join(timeout=1.0)

def _debug_broadcast_worker():
    """Background worker that polls nodes and broadcasts to all connected clients.
    Uses the SSE handler registry to dynamically discover what to broadcast."""
    last_throttle_update = {}  # handler_key -> last_update_time
    
    while debug_broadcast_running:
        try:
            # Only poll if there are connected clients
            if not debug_message_queues:
                time.sleep(0.1)
                continue
            
            current_time = time.time()
            messages_sent = False
            
            # Iterate all deployed engines
            for wid, engine in list(_deployed_engines.items()):
                if not engine.running:
                    continue
                
                # Get errors from system error node
                all_errors = engine.get_system_errors()
                if all_errors:
                    data = {'type': 'errors', 'data': all_errors, 'workflowId': wid}
                    _broadcast_to_all_clients(data)
                    engine.clear_system_errors()
                    messages_sent = True
                
                # Poll all nodes that have registered SSE handlers
                for node_id, node in engine.nodes.items():
                    if node.type not in _sse_handler_registry:
                        continue
                    
                    for handler_def in _sse_handler_registry[node.type]:
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
                            
                            _broadcast_to_all_clients(data)
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

def _broadcast_to_all_clients(data):
    """Send data to all connected SSE clients."""
    dead_clients = []
    for client_id, q in list(debug_message_queues.items()):
        try:
            q.put_nowait(data)
        except queue.Full:
            # Client queue is full, skip
            pass
        except Exception:
            dead_clients.append(client_id)
    
    # Clean up dead clients
    if dead_clients:
        with _clients_lock:
            for client_id in dead_clients:
                debug_message_queues.pop(client_id, None)

def _prune_backups(backup_dir):
    """Delete oldest backups so at most MAX_BACKUPS remain.

    Backup filenames embed a timestamp (workflow_YYYYMMDD_HHMMSS.json), so a
    lexical sort orders them chronologically.
    """
    try:
        backups = sorted(
            f for f in os.listdir(backup_dir)
            if f.startswith('workflow_') and f.endswith('.json')
        )
        for stale in backups[:-MAX_BACKUPS]:
            try:
                os.remove(os.path.join(backup_dir, stale))
            except OSError as e:
                logger.warning(f"Failed to prune backup {stale}: {e}")
    except OSError as e:
        logger.warning(f"Failed to prune backups in {backup_dir}: {e}")


def save_workflow_to_disk():
    """Save all workflows to disk atomically, with bounded backups."""
    try:
        # Backup existing workflow if it exists
        if os.path.exists(WORKFLOW_FILE):
            try:
                backup_dir = os.path.join(WORKFLOWS_DIR, '_backups')
                os.makedirs(backup_dir, exist_ok=True)

                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_file = os.path.join(backup_dir, f'workflow_{timestamp}.json')
                shutil.copy2(WORKFLOW_FILE, backup_file)
                logger.info(f"Backed up workflow to {backup_file}")
                _prune_backups(backup_dir)
            except (PermissionError, OSError) as e:
                logger.warning(f"Failed to create backup: {e}")

        # Build multi-workflow save data
        workflows_data = []
        with _state_lock:
            active_workflow = _active_workflow_id
            for wid, meta in _workflows.items():
                engine = _working_engines.get(wid)
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
        tmp_file = WORKFLOW_FILE + '.tmp'
        with open(tmp_file, 'w') as f:
            json.dump(save_data, f, indent=2)
        os.replace(tmp_file, WORKFLOW_FILE)
        logger.info(f"Saved {len(workflows_data)} workflow(s) to {WORKFLOW_FILE}")
        
    except PermissionError:
        logger.error(f"Permission denied when saving to {WORKFLOW_FILE}")
        logger.error("Please run the following command in terminal to fix ownership:")
        logger.error(f"  sudo chown -R $USER:$USER {WORKFLOWS_DIR}")
    except Exception as e:
        logger.error(f"Failed to save workflow: {e}")


def load_workflow_from_disk():
    """Load workflows from disk if file exists. Auto-migrates v1 format."""
    global _active_workflow_id
    try:
        if os.path.exists(WORKFLOW_FILE):
            with open(WORKFLOW_FILE, 'r') as f:
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
            with _state_lock:
                for wf in data.get('workflows', []):
                    wid = wf['id']
                    _workflows[wid] = {
                        'name': wf.get('name', 'Unnamed'),
                        'enabled': wf.get('enabled', True)
                    }
                    _working_engines[wid] = _create_workflow_engine()
                    _deployed_engines[wid] = _create_workflow_engine()
                    
                    wf_data = {
                        'nodes': wf.get('nodes', []),
                        'connections': wf.get('connections', [])
                    }
                    
                    # Import into both engines
                    _deployed_engines[wid].import_workflow(wf_data)
                    if _workflows[wid]['enabled']:
                        _deployed_engines[wid].start()
                    _working_engines[wid].import_workflow(wf_data)
                
                _active_workflow_id = data.get('activeWorkflow')
                # Ensure active workflow exists
                if _active_workflow_id not in _workflows and _workflows:
                    _active_workflow_id = next(iter(_workflows))
                
                total_nodes = sum(len(e.nodes) for e in _working_engines.values())
            logger.info(f"Loaded {len(_workflows)} workflow(s), {total_nodes} total nodes")
        else:
            # No workflow file - create default workflow
            _create_new_workflow(name='Workflow 1', workflow_id='workflow_1')
            _deployed_engines['workflow_1'].start()
            logger.info("No workflow file found, starting with empty workflow")
    except Exception as e:
        logger.error(f"Failed to load workflow: {e} (type: {type(e).__name__})")
        logger.debug("Full traceback:", exc_info=True)
        # On error, ensure at least one workflow exists
        if not _workflows:
            _create_new_workflow(name='Workflow 1', workflow_id='workflow_1')
        try:
            for engine in _deployed_engines.values():
                if not engine.running:
                    engine.start()
        except Exception as start_error:
            logger.error(f"Failed to start deployed engine during recovery: {start_error}")


@app.route('/')
def index():
    """Serve the main UI."""
    return send_from_directory(os.path.join(PKG_DIR, 'static'), 'index.html')


@app.route('/api/node-types', methods=['GET'])
def get_node_types():
    """Get all available node types (excluding system nodes like ErrorNode)."""
    global _node_types_cache
    if _node_types_cache is None:
        _build_node_types_cache()
    return jsonify(_node_types_cache)


# ==============================================================================
# Workflow Management API (Multi-Workflow)
# ==============================================================================

@app.route('/api/workflows', methods=['GET'])
def list_workflows():
    """List all workflows with metadata."""
    result = []
    with _state_lock:
        for wid, meta in _workflows.items():
            engine = _working_engines.get(wid)
            node_count = len(engine.nodes) if engine else 0
            result.append({
                'id': wid,
                'name': meta['name'],
                'enabled': meta['enabled'],
                'nodeCount': node_count,
                'active': wid == _active_workflow_id
            })
    return jsonify(result)


@app.route('/api/workflows', methods=['POST'])
def create_workflow():
    """Create a new workflow."""
    data = _get_json_body(required=False)
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    name = data.get('name', 'New Workflow')
    
    with _state_lock:
        wid = _create_new_workflow(name=name)
        _deployed_engines[wid].start()
        meta = dict(_workflows[wid])
    save_workflow_to_disk()
    
    return jsonify({
        'id': wid,
        'name': meta['name'],
        'enabled': meta['enabled']
    }), 201


@app.route('/api/workflows/<workflow_id>', methods=['PUT'])
def update_workflow(workflow_id):
    """Update workflow metadata (name, enabled)."""
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    with _state_lock:
        if workflow_id not in _workflows:
            return jsonify({'success': False, 'error': 'Workflow not found'}), 404
        
        meta = _workflows[workflow_id]
        
        if 'name' in data:
            new_name = _unique_workflow_name(data['name'], exclude_id=workflow_id)
            meta['name'] = new_name
        
        if 'enabled' in data:
            meta['enabled'] = data['enabled']
            deployed = _deployed_engines.get(workflow_id)
            if deployed:
                if data['enabled'] and not deployed.running:
                    deployed.start()
                elif not data['enabled'] and deployed.running:
                    deployed.stop()
        
        result = {'id': workflow_id, 'name': meta['name'], 'enabled': meta['enabled']}
    
    save_workflow_to_disk()
    
    return jsonify(result)


@app.route('/api/workflows/<workflow_id>', methods=['DELETE'])
def delete_workflow(workflow_id):
    """Delete a workflow."""
    global _active_workflow_id
    with _state_lock:
        if workflow_id not in _workflows:
            return jsonify({'success': False, 'error': 'Workflow not found'}), 404
        
        # Don't allow deleting the last workflow
        if len(_workflows) <= 1:
            return jsonify({'success': False, 'error': 'Cannot delete the last workflow'}), 400
        
        # Stop and remove engines
        deployed = _deployed_engines.get(workflow_id)
        if deployed and deployed.running:
            deployed.stop()
        
        del _workflows[workflow_id]
        _working_engines.pop(workflow_id, None)
        _deployed_engines.pop(workflow_id, None)
        
        # If active workflow was deleted, switch to first remaining
        if _active_workflow_id == workflow_id:
            _active_workflow_id = next(iter(_workflows))
        active = _active_workflow_id
    
    save_workflow_to_disk()
    return jsonify({'success': True, 'activeWorkflow': active})


@app.route('/api/workflows/active', methods=['PUT'])
def set_active_workflow():
    """Set the active workflow."""
    global _active_workflow_id
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    wid = data.get('workflowId')
    
    with _state_lock:
        if wid not in _workflows:
            return jsonify({'success': False, 'error': 'Workflow not found'}), 404
        
        _active_workflow_id = wid
    return jsonify({'success': True, 'activeWorkflow': wid})


@app.route('/api/nodes', methods=['GET'])
def get_nodes():
    """Get all nodes in the working workflow."""
    wid = _get_workflow_id_from_request()
    engine = _get_working_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    node_list = [node.to_dict() for node in engine.nodes.values()]
    return jsonify(node_list)


@app.route('/api/nodes', methods=['POST'])
def create_node():
    """Create a new node in working workflow."""
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    node_type = data.get('type')
    node_id = data.get('id')
    name = data.get('name', '')
    config = data.get('config', {})
    wid = _get_workflow_id_from_request()
    engine = _get_working_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    
    try:
        node = engine.create_node(node_type, node_id, name, config)
        # Set position if provided
        if 'x' in data:
            node.x = data.get('x', 0)
        if 'y' in data:
            node.y = data.get('y', 0)
        return jsonify(node.to_dict()), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/nodes/<node_id>', methods=['GET'])
def get_node(node_id):
    """Get a specific node from working workflow."""
    wid = _get_workflow_id_from_request()
    engine = _get_working_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    node = engine.get_node(node_id)
    if node:
        return jsonify(node.to_dict())
    return jsonify({'success': False, 'error': 'Node not found'}), 404


@app.route('/api/nodes/<node_id>', methods=['PUT'])
def update_node(node_id):
    """Update a node's configuration in working workflow."""
    wid = _get_workflow_id_from_request()
    engine = _get_working_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    node = engine.get_node(node_id)
    if not node:
        return jsonify({'success': False, 'error': 'Node not found'}), 404

    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)

    if 'name' in data:
        node.name = data['name']
    if 'config' in data:
        node.configure(data['config'])
    if 'enabled' in data:
        node.enabled = data['enabled']
    
    return jsonify(node.to_dict())


@app.route('/api/nodes/<node_id>', methods=['DELETE'])
def delete_node(node_id):
    """Delete a node from working workflow."""
    wid = _get_workflow_id_from_request()
    engine = _get_working_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    try:
        engine.delete_node(node_id)
        return '', 204
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/nodes/<node_id>/position', methods=['PUT'])
def update_node_position(node_id):
    """Update a node's position in working workflow."""
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    wid = _get_workflow_id_from_request()
    engine = _get_working_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    try:
        node = engine.nodes.get(node_id)
        if not node:
            return jsonify({'success': False, 'error': 'Node not found'}), 404
        
        node.x = data.get('x', 0)
        node.y = data.get('y', 0)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/nodes/<node_id>/enabled', methods=['POST'])
def set_node_enabled(node_id):
    """Set node enabled state (doesn't require redeployment)."""
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    enabled = data.get('enabled', True)
    
    try:
        # Update BOTH working and deployed engines so state is preserved.
        # Snapshot engine references under the lock, then work on them outside.
        with _state_lock:
            engine_pairs = [
                (_working_engines.get(wid), _deployed_engines.get(wid))
                for wid in _workflows
            ]

        for working, deployed in engine_pairs:
            working_node = working.nodes.get(node_id) if working else None
            deployed_node = deployed.nodes.get(node_id) if deployed else None

            if working_node:
                working_node.enabled = enabled
            if deployed_node:
                deployed_node.enabled = enabled

        # Save workflow to persist the state
        save_workflow_to_disk()
        
        return jsonify({'success': True, 'enabled': enabled})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/nodes/<node_id>/enabled', methods=['GET'])
def get_node_enabled(node_id):
    """Get node enabled state."""
    try:
        # Search all workflows for this node (snapshot refs under the lock)
        with _state_lock:
            engine_pairs = [
                (_working_engines.get(wid), _deployed_engines.get(wid))
                for wid in _workflows
            ]

        node = None
        for working, deployed in engine_pairs:
            node = ((deployed.nodes.get(node_id) if deployed else None)
                    or (working.nodes.get(node_id) if working else None))
            if node:
                break

        if not node:
            return jsonify({'success': False, 'error': 'Node not found'}), 404
        
        return jsonify({'enabled': node.enabled})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/connections', methods=['POST'])
def create_connection():
    """Create a connection between two nodes in working workflow."""
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    source_id = data.get('source')
    target_id = data.get('target')
    source_output = data.get('sourceOutput', 0)
    target_input = data.get('targetInput', 0)
    wid = _get_workflow_id_from_request()
    engine = _get_working_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    
    try:
        engine.connect_nodes(source_id, target_id, source_output, target_input)
        return jsonify({
            'source': source_id,
            'target': target_id,
            'sourceOutput': source_output,
            'targetInput': target_input
        }), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/connections', methods=['DELETE'])
def delete_connection():
    """Delete a connection between two nodes in working workflow."""
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    source_id = data.get('source')
    target_id = data.get('target')
    source_output = data.get('sourceOutput', 0)
    wid = _get_workflow_id_from_request()
    engine = _get_working_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    
    try:
        engine.disconnect_nodes(source_id, target_id, source_output)
        return '', 204
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/workflow', methods=['GET'])
def get_workflow():
    """Export the working workflow for the active/requested workflow."""
    wid = _get_workflow_id_from_request()
    with _state_lock:
        engine = _get_working_engine(wid)
        meta = dict(_workflows[wid]) if wid in _workflows else None
    if not engine or meta is None:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    result = engine.export_workflow()
    result['id'] = wid
    result['name'] = meta['name']
    result['enabled'] = meta['enabled']
    return jsonify(result)


@app.route('/api/workflow/deployed', methods=['GET'])
def get_deployed_workflow():
    """Export the deployed workflow."""
    wid = _get_workflow_id_from_request()
    engine = _get_deployed_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    return jsonify(engine.export_workflow())


@app.route('/api/workflow', methods=['POST'])
def import_workflow():
    """Import a workflow into both working and deployed engines (full deploy for one workflow)."""
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    wid = _get_workflow_id_from_request()
    with _state_lock:
        working = _get_working_engine(wid)
        deployed = _get_deployed_engine(wid)
        enabled = _workflows[wid]['enabled'] if wid in _workflows else False
    if not working or not deployed:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    try:
        deployed.stop()
        working.import_workflow(data)
        deployed.import_workflow(data)
        save_workflow_to_disk()
        if enabled:
            deployed.start()
        result = working.export_workflow()
        result['id'] = wid
        return jsonify(result), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/workflow/save', methods=['POST'])
def save_workflow():
    """Deploy all workflows - full deploy across all workflows."""
    try:
        # Snapshot state under the lock; do slow engine work outside it.
        # Engines have their own internal RLock, so holding a reference is safe
        # even if the workflow is concurrently deleted.
        with _state_lock:
            snapshot = [
                (wid, _working_engines.get(wid), _deployed_engines.get(wid),
                 meta['enabled'])
                for wid, meta in _workflows.items()
            ]

        for wid, working, deployed, enabled in snapshot:
            if not working or not deployed:
                continue

            # Export from working engine
            workflow_data = working.export_workflow()

            # Preserve runtime state from deployed engine
            for node_data in workflow_data.get('nodes', []):
                node_id = node_data['id']
                deployed_node = deployed.nodes.get(node_id)
                if deployed_node:
                    node_data['enabled'] = deployed_node.enabled

            # Stop deployed engine and import new workflow
            deployed.stop()
            deployed.import_workflow(workflow_data)

            # Also update working engine with preserved states
            working.import_workflow(workflow_data)

            # Start if workflow is enabled
            if enabled:
                deployed.start()

        save_workflow_to_disk()
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/workflow/deploy-changes', methods=['POST'])
def deploy_changes():
    """Incrementally deploy only changed nodes for a specific workflow."""
    try:
        data = _get_json_body()
        if data is None:
            return _json_error(_INVALID_BODY_ERROR, 400)
        with _state_lock:
            wid = data.get('workflowId', _active_workflow_id)
            working = _working_engines.get(wid)
            deployed = _deployed_engines.get(wid)
        if not working or not deployed:
            return jsonify({'success': False, 'error': 'Workflow not found'}), 404
        
        modified_nodes = data.get('modifiedNodes', [])
        added_nodes = data.get('addedNodes', [])
        deleted_nodes = data.get('deletedNodes', [])
        added_connections = data.get('addedConnections', [])
        deleted_connections = data.get('deletedConnections', [])
        
        nodes_restarted = 0
        
        # 1. Delete removed connections first
        for conn in deleted_connections:
            try:
                deployed.disconnect_nodes(
                    conn['source'], 
                    conn['target'], 
                    conn.get('sourceOutput', 0)
                )
                working.disconnect_nodes(
                    conn['source'], 
                    conn['target'], 
                    conn.get('sourceOutput', 0)
                )
            except Exception as e:
                logger.error(f"Error deleting connection: {e}")
        
        # 2. Delete removed nodes
        for node_id in deleted_nodes:
            try:
                node = deployed.get_node(node_id)
                if node:
                    node.on_stop()
                deployed.delete_node(node_id)
                working.delete_node(node_id)
                nodes_restarted += 1
            except Exception as e:
                logger.error(f"Error deleting node {node_id}: {e}")
        
        # 3. Add new nodes
        for node_data in added_nodes:
            try:
                node = deployed.create_node(
                    node_type=node_data['type'],
                    node_id=node_data['id'],
                    name=node_data.get('name', ''),
                    config=node_data.get('config', {})
                )
                node.enabled = node_data.get('enabled', True)
                node.x = node_data.get('x', 0)
                node.y = node_data.get('y', 0)
                
                if deployed.running:
                    node.on_start()
                
                w_node = working.create_node(
                    node_type=node_data['type'],
                    node_id=node_data['id'],
                    name=node_data.get('name', ''),
                    config=node_data.get('config', {})
                )
                w_node.enabled = node_data.get('enabled', True)
                w_node.x = node_data.get('x', 0)
                w_node.y = node_data.get('y', 0)
                
                nodes_restarted += 1
            except Exception as e:
                logger.error(f"Error adding node: {e}")
        
        # 4. Update modified nodes (stop, reconfigure, restart)
        for node_data in modified_nodes:
            node_id = node_data['id']
            try:
                deployed_node = deployed.get_node(node_id)
                working_node = working.get_node(node_id)
                
                if deployed_node:
                    deployed_node.on_stop()
                    deployed_node.name = node_data.get('name', deployed_node.name)
                    deployed_node.configure(node_data.get('config', {}))
                    deployed_node.enabled = node_data.get('enabled', True)
                    deployed_node.x = node_data.get('x', 0)
                    deployed_node.y = node_data.get('y', 0)
                    if deployed.running:
                        deployed_node.on_start()
                    nodes_restarted += 1
                
                if working_node:
                    working_node.name = node_data.get('name', working_node.name)
                    working_node.configure(node_data.get('config', {}))
                    working_node.enabled = node_data.get('enabled', True)
                    working_node.x = node_data.get('x', 0)
                    working_node.y = node_data.get('y', 0)
                    
            except Exception as e:
                logger.error(f"Error updating node {node_id}: {e}")
        
        # 5. Add new connections
        for conn in added_connections:
            try:
                deployed.connect_nodes(
                    conn['source'],
                    conn['target'],
                    conn.get('sourceOutput', 0),
                    conn.get('targetInput', 0)
                )
                working.connect_nodes(
                    conn['source'],
                    conn['target'],
                    conn.get('sourceOutput', 0),
                    conn.get('targetInput', 0)
                )
            except Exception as e:
                logger.error(f"Error adding connection: {e}")
        
        save_workflow_to_disk()
        
        return jsonify({
            'success': True, 
            'nodesRestarted': nodes_restarted
        }), 200
        
    except Exception as e:
        logger.error(f"Error in incremental deploy: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/workflow/restart', methods=['POST'])
def restart_workflow():
    """Restart all deployed workflows."""
    try:
        # Snapshot under the lock; engine stop/start happens outside it.
        with _state_lock:
            snapshot = [
                (wid, _deployed_engines.get(wid), meta['enabled'])
                for wid, meta in _workflows.items()
            ]

        for wid, deployed, enabled in snapshot:
            if not deployed:
                continue
            workflow_data = deployed.export_workflow()
            deployed.stop()
            deployed.import_workflow(workflow_data)
            if enabled:
                deployed.start()

        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Error restarting workflow: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/workflow/stats', methods=['GET'])
def get_workflow_stats():
    """Get deployed workflow statistics."""
    wid = _get_workflow_id_from_request()
    engine = _get_deployed_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    return jsonify(engine.get_workflow_stats())


# ==============================================================================
# MQTT Service Management API
# ==============================================================================

@app.route('/api/services/mqtt', methods=['GET'])
def list_mqtt_services():
    """List all MQTT services."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        services = mqtt_manager.list_services()
        return jsonify({'success': True, 'services': services})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/services/mqtt', methods=['POST'])
def create_mqtt_service():
    """Create a new MQTT service."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        data = _get_json_body()
        if data is None:
            return _json_error(_INVALID_BODY_ERROR, 400)

        # Validate required fields
        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Service name is required'}), 400
        if not data.get('broker'):
            return jsonify({'success': False, 'error': 'Broker address is required'}), 400
        
        service = mqtt_manager.create_service(data)
        return jsonify({
            'success': True,
            'service': {
                'id': service.id,
                'name': service.name,
                'broker': service.broker,
                'port': service.port
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/services/mqtt/<service_id>', methods=['GET'])
def get_mqtt_service(service_id):
    """Get a specific MQTT service by ID."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        service = mqtt_manager.get_service(service_id)
        if not service:
            return jsonify({'success': False, 'error': 'Service not found'}), 404
        
        return jsonify({
            'success': True,
            'service': service.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/services/mqtt/<service_id>', methods=['PUT'])
def update_mqtt_service(service_id):
    """Update an existing MQTT service."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        data = _get_json_body()
        if data is None:
            return _json_error(_INVALID_BODY_ERROR, 400)

        service = mqtt_manager.update_service(service_id, data)
        if not service:
            return jsonify({'success': False, 'error': 'Service not found'}), 404
        
        return jsonify({
            'success': True,
            'service': service.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/services/mqtt/<service_id>', methods=['DELETE'])
def delete_mqtt_service(service_id):
    """Delete an MQTT service."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        
        if not mqtt_manager.delete_service(service_id):
            return jsonify({
                'success': False, 
                'error': 'Service not found or still in use'
            }), 400
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/services/mqtt/<service_id>/test', methods=['POST'])
def test_mqtt_service(service_id):
    """Test connection to an MQTT service."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        
        service = mqtt_manager.get_service(service_id)
        if not service:
            return jsonify({'success': False, 'error': 'Service not found'}), 404
        
        # Try to connect
        connected = service.connect()
        
        return jsonify({
            'success': True,
            'connected': connected,
            'status': 'connected' if connected else 'failed'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==============================================================================
# File Upload API
# ==============================================================================

@app.route('/api/upload/file', methods=['POST'])
def upload_file():
    """Upload a file (model, video, etc.) and save to the server."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        if not file.filename or file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Determine upload directory from optional 'directory' field, default to models.
        # Only allowlisted subdirectory names are accepted (no separators, no
        # traversal) and the resolved path must stay inside UPLOAD_BASE_DIR.
        upload_subdir = request.form.get('directory', 'models')
        normalized_subdir = os.path.normpath(upload_subdir).replace('\\', '/')
        if normalized_subdir not in ALLOWED_UPLOAD_SUBDIRS:
            return jsonify({
                'success': False,
                'error': f"Invalid upload directory. Allowed: {', '.join(ALLOWED_UPLOAD_SUBDIRS)}"
            }), 400

        base_dir = os.path.realpath(UPLOAD_BASE_DIR)
        upload_dir = os.path.realpath(os.path.join(base_dir, normalized_subdir))
        if upload_dir != base_dir and not upload_dir.startswith(base_dir + os.sep):
            return jsonify({
                'success': False,
                'error': 'Invalid upload directory: outside allowed base'
            }), 400
        os.makedirs(upload_dir, exist_ok=True)

        # Save the file
        filename = os.path.basename(file.filename)
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)
        
        return jsonify({
            'success': True,
            'model_path': file_path,
            'file_path': file_path,
            'filename': filename
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def _get_declared_actions(node):
    """Collect the union of 'actions' declared across the node's class hierarchy."""
    declared = set()
    for klass in type(node).__mro__:
        declared.update(getattr(klass, 'actions', None) or [])
    return declared


@app.route('/api/nodes/<node_id>/<action>', methods=['POST'])
def trigger_node_action(node_id, action):
    """Trigger a button action on a node in deployed workflow.

    Only actions explicitly declared in the node class's `actions` list may be
    invoked; anything else (including private/underscore names) returns 404.
    """
    try:
        node, _ = _find_deployed_node(node_id)
        if not node:
            return jsonify({'success': False, 'error': 'Node not found'}), 404

        # Only allow explicitly declared, public action names
        if action.startswith('_') or action not in _get_declared_actions(node):
            return jsonify({'success': False, 'error': f'Action {action} not found on node'}), 404

        method = getattr(node, action, None)
        if not callable(method):
            return jsonify({'success': False, 'error': f'{action} is not a callable method'}), 400

        method()
        return jsonify({'success': True, 'status': 'success', 'action': action})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/debug/stream')
def debug_stream():
    """Server-Sent Events stream for debug messages."""
    def generate():
        # Create a queue for this client
        q = queue.Queue(maxsize=100)
        client_id = id(q)
        with _clients_lock:
            debug_message_queues[client_id] = q
        
        # Start broadcast thread if not running
        start_debug_broadcast()
        
        try:
            yield 'data: {"type": "connected"}\n\n'
            
            while True:
                try:
                    # Wait for data from broadcast thread
                    data = q.get(timeout=1.0)
                    yield f'data: {json.dumps(data)}\n\n'
                except queue.Empty:
                    # Send keepalive
                    yield 'data: {"type": "keepalive"}\n\n'
                    
        except GeneratorExit:
            # Client disconnected
            with _clients_lock:
                debug_message_queues.pop(client_id, None)
        except Exception as e:
            # Log error and close connection
            logger.error(f"SSE Error: {e}")
            with _clients_lock:
                debug_message_queues.pop(client_id, None)
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')
