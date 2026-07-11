"""Workflow management API: CRUD, active switching, export/import,
full deploy (save), incremental deploy (deploy-changes), restart and stats.
"""

import logging

from flask import Blueprint, jsonify

from pynode.api.helpers import (
    _INVALID_BODY_ERROR,
    _get_deployed_engine,
    _get_json_body,
    _get_manager,
    _get_working_engine,
    _get_workflow_id_from_request,
    _json_error,
)

logger = logging.getLogger(__name__)

workflows_bp = Blueprint('workflows', __name__)


@workflows_bp.route('/api/workflows', methods=['GET'])
def list_workflows():
    """List all workflows with metadata."""
    manager = _get_manager()
    result = []
    with manager.state_lock:
        for wid, meta in manager.workflows.items():
            engine = manager.working_engines.get(wid)
            deployed = manager.deployed_engines.get(wid)
            node_count = len(engine.nodes) if engine else 0
            result.append({
                'id': wid,
                'name': meta['name'],
                'enabled': meta['enabled'],
                'nodeCount': node_count,
                'active': wid == manager.active_workflow_id,
                'running': bool(deployed.running) if deployed else False
            })
    return jsonify(result)


@workflows_bp.route('/api/workflows', methods=['POST'])
def create_workflow():
    """Create a new workflow."""
    manager = _get_manager()
    data = _get_json_body(required=False)
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    name = data.get('name', 'New Workflow')

    with manager.state_lock:
        wid = manager.create_new_workflow(name=name)
        manager.deployed_engines[wid].start()
        meta = dict(manager.workflows[wid])
    manager.save_workflow_to_disk()

    return jsonify({
        'id': wid,
        'name': meta['name'],
        'enabled': meta['enabled']
    }), 201


@workflows_bp.route('/api/workflows/<workflow_id>', methods=['PUT'])
def update_workflow(workflow_id):
    """Update workflow metadata (name, enabled)."""
    manager = _get_manager()
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    with manager.state_lock:
        if workflow_id not in manager.workflows:
            return jsonify({'success': False, 'error': 'Workflow not found'}), 404

        meta = manager.workflows[workflow_id]

        if 'name' in data:
            new_name = manager.unique_workflow_name(data['name'], exclude_id=workflow_id)
            meta['name'] = new_name

        if 'enabled' in data:
            meta['enabled'] = data['enabled']
            deployed = manager.deployed_engines.get(workflow_id)
            if deployed:
                if data['enabled'] and not deployed.running:
                    deployed.start()
                elif not data['enabled'] and deployed.running:
                    deployed.stop()

        result = {'id': workflow_id, 'name': meta['name'], 'enabled': meta['enabled']}

    manager.save_workflow_to_disk()

    return jsonify(result)


@workflows_bp.route('/api/workflows/<workflow_id>', methods=['DELETE'])
def delete_workflow(workflow_id):
    """Delete a workflow."""
    manager = _get_manager()
    with manager.state_lock:
        if workflow_id not in manager.workflows:
            return jsonify({'success': False, 'error': 'Workflow not found'}), 404

        # Don't allow deleting the last workflow
        if len(manager.workflows) <= 1:
            return jsonify({'success': False, 'error': 'Cannot delete the last workflow'}), 400

        # Stop and remove engines
        deployed = manager.deployed_engines.get(workflow_id)
        if deployed and deployed.running:
            deployed.stop()

        del manager.workflows[workflow_id]
        manager.working_engines.pop(workflow_id, None)
        manager.deployed_engines.pop(workflow_id, None)

        # If active workflow was deleted, switch to first remaining
        if manager.active_workflow_id == workflow_id:
            manager.active_workflow_id = next(iter(manager.workflows))
        active = manager.active_workflow_id

    manager.save_workflow_to_disk()
    return jsonify({'success': True, 'activeWorkflow': active})


@workflows_bp.route('/api/workflows/active', methods=['PUT'])
def set_active_workflow():
    """Set the active workflow."""
    manager = _get_manager()
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    wid = data.get('workflowId')

    with manager.state_lock:
        if wid not in manager.workflows:
            return jsonify({'success': False, 'error': 'Workflow not found'}), 404

        manager.active_workflow_id = wid
    return jsonify({'success': True, 'activeWorkflow': wid})


@workflows_bp.route('/api/workflow', methods=['GET'])
def get_workflow():
    """Export the working workflow for the active/requested workflow."""
    manager = _get_manager()
    wid = _get_workflow_id_from_request()
    with manager.state_lock:
        engine = _get_working_engine(wid)
        meta = dict(manager.workflows[wid]) if wid in manager.workflows else None
    if not engine or meta is None:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    result = engine.export_workflow()
    result['id'] = wid
    result['name'] = meta['name']
    result['enabled'] = meta['enabled']
    return jsonify(result)


@workflows_bp.route('/api/workflow/deployed', methods=['GET'])
def get_deployed_workflow():
    """Export the deployed workflow."""
    wid = _get_workflow_id_from_request()
    engine = _get_deployed_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    return jsonify(engine.export_workflow())


@workflows_bp.route('/api/workflow', methods=['POST'])
def import_workflow():
    """Import a workflow into both working and deployed engines (full deploy for one workflow)."""
    manager = _get_manager()
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    wid = _get_workflow_id_from_request()
    with manager.state_lock:
        working = _get_working_engine(wid)
        deployed = _get_deployed_engine(wid)
        enabled = manager.workflows[wid]['enabled'] if wid in manager.workflows else False
    if not working or not deployed:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    try:
        deployed.stop()
        working.import_workflow(data)
        deployed.import_workflow(data)
        manager.save_workflow_to_disk()
        if enabled:
            deployed.start()
        result = working.export_workflow()
        result['id'] = wid
        return jsonify(result), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@workflows_bp.route('/api/workflow/save', methods=['POST'])
def save_workflow():
    """Deploy all workflows - full deploy across all workflows."""
    manager = _get_manager()
    try:
        # Snapshot state under the lock; do slow engine work outside it.
        # Engines have their own internal RLock, so holding a reference is safe
        # even if the workflow is concurrently deleted.
        with manager.state_lock:
            snapshot = [
                (wid, manager.working_engines.get(wid), manager.deployed_engines.get(wid),
                 meta['enabled'])
                for wid, meta in manager.workflows.items()
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

        manager.save_workflow_to_disk()
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@workflows_bp.route('/api/workflow/deploy-changes', methods=['POST'])
def deploy_changes():
    """Incrementally deploy only changed nodes for a specific workflow."""
    manager = _get_manager()
    try:
        data = _get_json_body()
        if data is None:
            return _json_error(_INVALID_BODY_ERROR, 400)
        with manager.state_lock:
            wid = data.get('workflowId', manager.active_workflow_id)
            working = manager.working_engines.get(wid)
            deployed = manager.deployed_engines.get(wid)
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

        # 6. If the workflow is enabled but its deployed engine is not
        # running (e.g. after a transient /api/workflow/stop), start it so
        # hitting Deploy resumes processing. engine.start() calls on_start()
        # on every node, including any added/modified above that were not
        # started individually because the engine was stopped. When the
        # engine is already running (the normal case) this is a no-op.
        with manager.state_lock:
            enabled = manager.workflows.get(wid, {}).get('enabled', False)
        if enabled and not deployed.running:
            deployed.start()

        manager.save_workflow_to_disk()

        return jsonify({
            'success': True,
            'nodesRestarted': nodes_restarted
        }), 200

    except Exception as e:
        logger.error(f"Error in incremental deploy: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400


@workflows_bp.route('/api/workflow/restart', methods=['POST'])
def restart_workflow():
    """Restart all deployed workflows."""
    manager = _get_manager()
    try:
        # Snapshot under the lock; engine stop/start happens outside it.
        with manager.state_lock:
            snapshot = [
                (wid, manager.deployed_engines.get(wid), meta['enabled'])
                for wid, meta in manager.workflows.items()
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


@workflows_bp.route('/api/workflow/stop', methods=['POST'])
def stop_workflows():
    """Transiently stop ALL deployed workflow engines.

    Unlike disabling a workflow, this does NOT change any workflow's
    persisted 'enabled' flag and does NOT write to disk - the next Deploy
    (full save or incremental deploy-changes) starts enabled workflows again.
    """
    manager = _get_manager()
    try:
        # Snapshot under the lock; engine stop happens outside it.
        with manager.state_lock:
            snapshot = [manager.deployed_engines.get(wid)
                        for wid in manager.workflows]

        stopped = 0
        for deployed in snapshot:
            if deployed and deployed.running:
                deployed.stop()
                stopped += 1

        return jsonify({'success': True, 'stopped': stopped}), 200
    except Exception as e:
        logger.error(f"Error stopping workflows: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400


@workflows_bp.route('/api/workflow/stats', methods=['GET'])
def get_workflow_stats():
    """Get deployed workflow statistics."""
    wid = _get_workflow_id_from_request()
    engine = _get_deployed_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    return jsonify(engine.get_workflow_stats())
