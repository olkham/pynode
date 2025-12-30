"""
MQTT In node - subscribes to MQTT topics and receives messages.
Uses shared MQTT service for connection management.
"""

import json
from typing import Any, Dict, Optional
from nodes.base_node import BaseNode
from nodes.MQTTNode.mqtt_service import mqtt_manager, MQTTService


class MqttInNode(BaseNode):
    """
    MQTT In node - subscribes to MQTT topics and receives messages.
    Uses a shared MQTT service for the broker connection.
    """
    display_name = 'MQTT In'
    icon = '📥'
    category = 'network'
    color = '#87A980'
    border_color = '#5F7858'
    text_color = '#000000'
    input_count = 0
    output_count = 1
    
    DEFAULT_CONFIG = {
        'serviceId': '',
        'topic': 'test/topic',
        'qos': '0'
    }
    
    properties = [
        {
            'name': 'serviceId',
            'label': 'MQTT Broker',
            'type': 'mqtt-service',
            'default': DEFAULT_CONFIG['serviceId'],
            'help': 'Select or create an MQTT broker connection'
        },
        {
            'name': 'topic',
            'label': 'Topic',
            'type': 'text',
            'default': DEFAULT_CONFIG['topic'],
            'help': 'MQTT topic to subscribe to (supports wildcards)'
        },
        {
            'name': 'qos',
            'label': 'QoS',
            'type': 'select',
            'options': [
                {'value': '0', 'label': '0 - At most once'},
                {'value': '1', 'label': '1 - At least once'},
                {'value': '2', 'label': '2 - Exactly once'}
            ],
            'default': DEFAULT_CONFIG['qos']
        }
    ]
    
    def __init__(self, node_id: str = None, name: str = ""):
        super().__init__(node_id, name)
        self._service: Optional[MQTTService] = None
        self._subscribed_topic: Optional[str] = None
    
    def _on_message(self, topic: str, payload: bytes):
        """Callback when message is received from the service."""
        try:
            decoded = payload.decode('utf-8')
            # Try to parse as JSON
            try:
                decoded = json.loads(decoded)
            except (json.JSONDecodeError, ValueError):
                pass
            payload_data = decoded
        except:
            payload_data = payload
        
        msg = self.create_message(
            payload=payload_data,
            topic=topic
        )
        self.send(msg)
    
    def on_start(self):
        """Subscribe to MQTT topic when workflow starts."""
        super().on_start()
        
        service_id = self.config.get('serviceId', '')
        if not service_id:
            self.report_error("No MQTT broker selected. Configure a broker in node properties.")
            return
        
        self._service = mqtt_manager.get_service(service_id)
        if not self._service:
            self.report_error(f"MQTT broker '{service_id}' not found. Please reconfigure.")
            return
        
        # Register with the service
        self._service.register_node(self.id, self.report_error)
        
        # Connect if not already connected
        if not self._service.connected:
            self._service.connect()
        
        # Subscribe to topic
        self._subscribed_topic = self.config.get('topic', 'test/topic')
        qos = self.get_config_int('qos', 0)
        self._service.subscribe(self.id, self._subscribed_topic, qos, self._on_message)
    
    def on_stop(self):
        """Unsubscribe and cleanup when workflow stops."""
        super().on_stop()
        
        if self._service and self._subscribed_topic:
            self._service.unsubscribe(self.id, self._subscribed_topic, self._on_message)
            self._service.unregister_node(self.id)
        
        self._service = None
        self._subscribed_topic = None
    
    def on_close(self):
        """Cleanup when node is removed."""
        self.on_stop()
