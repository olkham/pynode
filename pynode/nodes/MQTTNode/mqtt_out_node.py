"""
MQTT Out node - publishes messages to MQTT topics.
Uses shared MQTT service for connection management.
"""

from typing import Any, Dict, Optional
from pynode.nodes.base_node import BaseNode, Info
from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager, MQTTService

_info = Info()
_info.add_text("Publishes messages to an MQTT topic. Uses a shared broker connection that can be reused across multiple MQTT nodes.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message to publish. msg.payload becomes the MQTT message body")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("MQTT Broker:", "Select or configure a broker connection (host, port, credentials)"),
    ("Topic:", "MQTT topic to publish to (can be overridden by msg.topic)"),
    ("QoS:", "Quality of Service level (0=at most once, 1=at least once, 2=exactly once)"),
    ("Retain:", "If true, broker retains the last message for new subscribers")
)
_info.add_header("Input Message")
_info.add_code('msg.payload').text(" - Data to publish (objects are JSON-encoded)").end()
_info.add_code('msg.topic').text(" - Optional topic override").end()


class MqttOutNode(BaseNode):
    """
    MQTT Out node - publishes messages to MQTT topics.
    Uses a shared MQTT service for the broker connection.
    """
    info = str(_info)
    display_name = 'MQTT Out'
    icon = '📤'
    category = 'network'
    color = '#87A980'
    border_color = '#5F7858'
    text_color = '#000000'
    input_count = 1
    output_count = 0
    
    DEFAULT_CONFIG = {
        'serviceId': '',
        'topic': 'test/topic',
        'qos': '0',
        'retain': 'false'
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
            'help': 'MQTT topic to publish to (can be overridden by msg.topic)'
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
        },
        {
            'name': 'retain',
            'label': 'Retain',
            'type': 'select',
            'options': [
                {'value': 'false', 'label': 'False'},
                {'value': 'true', 'label': 'True'}
            ],
            'default': DEFAULT_CONFIG['retain']
        }
    ]
    
    def __init__(self, node_id: str = None, name: str = ""):
        super().__init__(node_id, name)
        self._service: Optional[MQTTService] = None
    
    def on_start(self):
        """Register with MQTT service when workflow starts."""
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
            success = self._service.connect()
            if not success:
                self.report_error(f"Failed to connect to MQTT broker {self._service.broker}:{self._service.port}")
                return
    
    def on_stop(self):
        """Unregister from service when workflow stops."""
        super().on_stop()
        
        if self._service:
            self._service.unregister_node(self.id)
        
        self._service = None
    
    def on_close(self):
        """Cleanup when node is removed."""
        self.on_stop()
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Process incoming message and publish to MQTT.
        """
        if not self._service:
            self.report_error("No MQTT broker configured")
            return
        
        if not self._service.connected:
            self.report_error(f"Cannot publish: not connected to MQTT broker {self._service.broker}:{self._service.port}")
            return
        
        topic = self.config.get('topic', 'test/topic')
        
        # Allow msg.topic to override configured topic
        if 'topic' in msg and msg['topic']:
            topic = msg['topic']
        
        # Validate topic
        if not topic or topic.strip() == '':
            self.report_error("Topic is empty. Configure a topic in node properties.")
            return
        
        qos = self.get_config_int('qos', 0)
        retain = self.get_config_bool('retain', False)
        payload = msg.get('payload', '')
        
        if not self._service.publish(topic, payload, qos, retain):
            self.report_error(f"Failed to publish to '{topic}'")
