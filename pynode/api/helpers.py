"""Shared helpers for the API blueprints.

Route handlers access the per-app WorkflowManager through ``_get_manager()``,
which reads it off ``current_app`` - so every blueprint works against
whichever app instance is handling the request (default instance or a fresh
``create_app()`` app in tests).
"""

from flask import current_app, jsonify, request

_INVALID_BODY_ERROR = 'Invalid or missing JSON body'


def _get_manager():
    """Return the WorkflowManager of the app handling the current request."""
    return current_app.extensions['workflow_manager']


def _json_error(message, status):
    """JSON error envelope: {'success': False, 'error': str}."""
    return jsonify({'success': False, 'error': message}), status


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


def _get_workflow_id_from_request():
    """Extract workflow_id from request query params, defaulting to active."""
    manager = _get_manager()
    with manager.state_lock:
        return request.args.get('workflow', manager.active_workflow_id)


def _get_working_engine(workflow_id=None):
    """Get working engine for a workflow, defaulting to active."""
    return _get_manager().get_working_engine(workflow_id)


def _get_deployed_engine(workflow_id=None):
    """Get deployed engine for a workflow, defaulting to active."""
    return _get_manager().get_deployed_engine(workflow_id)


def _find_deployed_node(node_id):
    """Find a node across all deployed engines. Returns (node, workflow_id) or (None, None)."""
    return _get_manager().find_deployed_node(node_id)


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
