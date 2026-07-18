"""MQTT service management API.

All handlers resolve the MQTT service manager off the current app
(``_get_mqtt_manager``) so the sandboxed test app operates on its own
isolated services file, never the real mqtt_services.json.
"""

from flask import Blueprint, jsonify

from pynode.api.helpers import (
    _INVALID_BODY_ERROR, _get_json_body, _get_mqtt_manager, _json_error)

services_bp = Blueprint('services', __name__)


@services_bp.route('/api/services/mqtt', methods=['GET'])
def list_mqtt_services():
    """List all MQTT services."""
    try:
        services = _get_mqtt_manager().list_services()
        return jsonify({'success': True, 'services': services})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@services_bp.route('/api/services/mqtt', methods=['POST'])
def create_mqtt_service():
    """Create a new MQTT service."""
    try:
        data = _get_json_body()
        if data is None:
            return _json_error(_INVALID_BODY_ERROR, 400)

        # Validate required fields
        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Service name is required'}), 400
        if not data.get('broker'):
            return jsonify({'success': False, 'error': 'Broker address is required'}), 400

        service = _get_mqtt_manager().create_service(data)
        return jsonify({'success': True, 'service': service.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@services_bp.route('/api/services/mqtt/test', methods=['POST'])
def test_mqtt_connection():
    """Test an MQTT connection using the SUBMITTED form values.

    Does not create or modify any saved service and does not disturb live
    connections - it spins up a short-lived throwaway client that is always
    cleaned up. Returns ``{'success': bool, 'error': str|None}`` where
    ``success`` reflects whether the connection succeeded.
    """
    try:
        from pynode.nodes.MQTTNode.mqtt_service import test_connection

        data = _get_json_body()
        if data is None:
            return _json_error(_INVALID_BODY_ERROR, 400)
        if not data.get('broker'):
            return jsonify({'success': False, 'error': 'Broker address is required'}), 400

        success, error = test_connection(data)
        return jsonify({'success': success, 'error': error})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@services_bp.route('/api/services/mqtt/<service_id>', methods=['GET'])
def get_mqtt_service(service_id):
    """Get a specific MQTT service by ID."""
    try:
        service = _get_mqtt_manager().get_service(service_id)
        if not service:
            return jsonify({'success': False, 'error': 'Service not found'}), 404

        return jsonify({'success': True, 'service': service.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@services_bp.route('/api/services/mqtt/<service_id>', methods=['PUT'])
def update_mqtt_service(service_id):
    """Update an existing MQTT service."""
    try:
        data = _get_json_body()
        if data is None:
            return _json_error(_INVALID_BODY_ERROR, 400)

        service = _get_mqtt_manager().update_service(service_id, data)
        if not service:
            return jsonify({'success': False, 'error': 'Service not found'}), 404

        return jsonify({'success': True, 'service': service.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@services_bp.route('/api/services/mqtt/<service_id>', methods=['DELETE'])
def delete_mqtt_service(service_id):
    """Delete an MQTT service."""
    try:
        if not _get_mqtt_manager().delete_service(service_id):
            return jsonify({
                'success': False,
                'error': 'Service not found or still in use'
            }), 400

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
