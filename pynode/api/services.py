"""MQTT service management API."""

from flask import Blueprint, jsonify

from pynode.api.helpers import _INVALID_BODY_ERROR, _get_json_body, _json_error

services_bp = Blueprint('services', __name__)


@services_bp.route('/api/services/mqtt', methods=['GET'])
def list_mqtt_services():
    """List all MQTT services."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        services = mqtt_manager.list_services()
        return jsonify({'success': True, 'services': services})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@services_bp.route('/api/services/mqtt', methods=['POST'])
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


@services_bp.route('/api/services/mqtt/<service_id>', methods=['GET'])
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


@services_bp.route('/api/services/mqtt/<service_id>', methods=['PUT'])
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


@services_bp.route('/api/services/mqtt/<service_id>', methods=['DELETE'])
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


@services_bp.route('/api/services/mqtt/<service_id>/test', methods=['POST'])
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
