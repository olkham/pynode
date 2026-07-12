"""Node API: node-types listing, node CRUD, position, enabled state,
connections, declared button actions, and the dynamic per-node-type routes
that node classes declare via ``api_routes``.
"""

import inspect
import os

from flask import Blueprint, Response, jsonify, request, stream_with_context

from pynode import node_registry
from pynode.api.helpers import (
    _INVALID_BODY_ERROR,
    _find_deployed_node,
    _get_json_body,
    _get_manager,
    _get_working_engine,
    _get_workflow_id_from_request,
    _json_error,
    _resolve_node_handler,
)

nodes_bp = Blueprint('nodes', __name__)


@nodes_bp.route('/api/node-types', methods=['GET'])
def get_node_types():
    """Get all available node types (excluding system nodes like ErrorNode)."""
    return jsonify(node_registry.get_node_types())


@nodes_bp.route('/api/nodes', methods=['GET'])
def get_nodes():
    """Get all nodes in the working workflow."""
    wid = _get_workflow_id_from_request()
    engine = _get_working_engine(wid)
    if not engine:
        return jsonify({'success': False, 'error': 'Workflow not found'}), 404
    node_list = [node.to_dict() for node in engine.nodes.values()]
    return jsonify(node_list)


@nodes_bp.route('/api/nodes', methods=['POST'])
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


@nodes_bp.route('/api/nodes/<node_id>', methods=['GET'])
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


@nodes_bp.route('/api/nodes/<node_id>', methods=['PUT'])
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


@nodes_bp.route('/api/nodes/<node_id>', methods=['DELETE'])
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


@nodes_bp.route('/api/nodes/<node_id>/position', methods=['PUT'])
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


@nodes_bp.route('/api/nodes/<node_id>/enabled', methods=['POST'])
def set_node_enabled(node_id):
    """Set node enabled state (doesn't require redeployment)."""
    manager = _get_manager()
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    enabled = data.get('enabled', True)

    try:
        # Update BOTH working and deployed engines so state is preserved.
        # Snapshot engine references under the lock, then work on them outside.
        with manager.state_lock:
            engine_pairs = [
                (manager.working_engines.get(wid), manager.deployed_engines.get(wid))
                for wid in manager.workflows
            ]

        for working, deployed in engine_pairs:
            working_node = working.nodes.get(node_id) if working else None
            deployed_node = deployed.nodes.get(node_id) if deployed else None

            if working_node:
                working_node.enabled = enabled
            if deployed_node:
                deployed_node.enabled = enabled

        # Save workflow to persist the state
        manager.save_workflow_to_disk()

        return jsonify({'success': True, 'enabled': enabled})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@nodes_bp.route('/api/nodes/<node_id>/enabled', methods=['GET'])
def get_node_enabled(node_id):
    """Get node enabled state."""
    manager = _get_manager()
    try:
        # Search all workflows for this node (snapshot refs under the lock)
        with manager.state_lock:
            engine_pairs = [
                (manager.working_engines.get(wid), manager.deployed_engines.get(wid))
                for wid in manager.workflows
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


@nodes_bp.route('/api/connections', methods=['POST'])
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


@nodes_bp.route('/api/connections', methods=['DELETE'])
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


def _get_declared_actions(node):
    """Collect the union of 'actions' declared across the node's class hierarchy."""
    declared = set()
    for klass in type(node).__mro__:
        declared.update(getattr(klass, 'actions', None) or [])
    return declared


def _action_accepts_arg(method):
    """Return True if `method` accepts at least one positional argument."""
    try:
        sig = inspect.signature(method)
    except (TypeError, ValueError):
        return False
    for param in sig.parameters.values():
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD,
                          param.VAR_POSITIONAL):
            return True
    return False


@nodes_bp.route('/api/nodes/<node_id>/<action>', methods=['POST'])
def trigger_node_action(node_id, action):
    """Trigger a button action on a node in deployed workflow.

    Only actions explicitly declared in the node class's `actions` list may be
    invoked; anything else (including private/underscore names) returns 404.

    Actions may optionally accept a single value supplied via a JSON body
    ``{"value": ...}`` (e.g. VideoReaderNode.seek(target)); zero-argument
    actions are called with no arguments.
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

        data = request.get_json(silent=True)
        if (isinstance(data, dict) and 'value' in data
                and _action_accepts_arg(method)):
            method(data['value'])
        else:
            method()
        return jsonify({'success': True, 'status': 'success', 'action': action})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==============================================================================
# Dynamic node endpoint registration (from node-class ``api_routes``)
# ==============================================================================

def _add_node_route(route, view_func, endpoint_name, methods):
    """Register a URL rule under the standard node API prefix."""
    nodes_bp.add_url_rule(
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


def _register_dynamic_node_routes():
    """Register routes for all node types that declare api_routes."""
    registered = set()

    for node_type_name, routes in node_registry.api_route_registry.items():
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


# Register all dynamic routes on the blueprint at import time (node classes
# are static); every app the blueprint is registered on gets them.
_register_dynamic_node_routes()
