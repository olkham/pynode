"""
MQTT Out node - publishes messages to MQTT topics.
"""

from typing import Any, Dict
from base_node import BaseNode

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


class MqttOutNode(BaseNode):
    """
    MQTT Out node - publishes messages to MQTT topics.
    """
    display_name = 'MQTT Out'
    icon = '📤'
    category = 'network'
    color = '#87A980'
    border_color = '#5F7858'
    text_color = '#000000'
    input_count = 1
    output_count = 0
    
    properties = [
        {
            'name': 'broker',
            'label': 'Broker',
            'type': 'text',
            'default': 'localhost',
            'help': 'MQTT broker address'
        },
        {
            'name': 'port',
            'label': 'Port',
            'type': 'text',
            'default': '1883',
            'help': 'MQTT broker port'
        },
        {
            'name': 'topic',
            'label': 'Topic',
            'type': 'text',
            'default': 'test/topic',
            'help': 'MQTT topic to publish to'
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
            'default': '0'
        },
        {
            'name': 'retain',
            'label': 'Retain',
            'type': 'select',
            'options': [
                {'value': 'false', 'label': 'False'},
                {'value': 'true', 'label': 'True'}
            ],
            'default': 'false'
        },
        {
            'name': 'clientId',
            'label': 'Client ID',
            'type': 'text',
            'default': '',
            'help': 'Leave blank for auto-generated'
        },
        {
            'name': 'username',
            'label': 'Username',
            'type': 'text',
            'default': ''
        },
        {
            'name': 'password',
            'label': 'Password',
            'type': 'text',
            'default': ''
        }
    ]
    
    def __init__(self, node_id: str = None, name: str = ""):
        super().__init__(node_id, name)
        self.client = None
        self._connected = False
        
        self.configure({
            'broker': 'localhost',
            'port': '1883',
            'topic': 'test/topic',
            'qos': '0',
            'retain': 'false',
            'clientId': '',
            'username': '',
            'password': ''
        })
    
    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker."""
        if rc == 0:
            self._connected = True
        else:
            self.report_error(f"Connection failed with code {rc}")
    
    def on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker."""
        self._connected = False
        if rc != 0:
            self.report_error("Unexpected disconnection from broker")
    
    def on_publish(self, client, userdata, mid):
        """Callback when message is published."""
        pass  # Could add logging here if needed
    
    def on_start(self):
        """Connect to MQTT broker when workflow starts."""
        super().on_start()  # Start base node worker thread
        
        if not MQTT_AVAILABLE:
            self.report_error("paho-mqtt not installed. Install with: pip install paho-mqtt")
            return
        
        broker = self.config.get('broker', 'localhost')
        port = int(self.config.get('port', '1883'))
        client_id = self.config.get('clientId', '') or f"pynode_out_{self.id[:8]}"
        username = self.config.get('username', '')
        password = self.config.get('password', '')
        
        try:
            self.client = mqtt.Client(client_id=client_id)
            self.client.on_connect = self.on_connect
            self.client.on_disconnect = self.on_disconnect
            self.client.on_publish = self.on_publish
            
            if username:
                self.client.username_pw_set(username, password)
            
            # Use blocking connect with timeout
            self.client.connect(broker, port, 60)
            self.client.loop_start()
            self._connected = True
            
        except Exception as e:
            self.report_error(f"Failed to connect to {broker}:{port} - {e}")
    
    def on_stop(self):
        """Disconnect from MQTT broker when workflow stops."""
        super().on_stop()  # Stop base node worker thread
        
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception as e:
                self.report_error(f"Error disconnecting: {e}")
    
    def on_close(self):
        """Cleanup when node is removed."""
        self.on_stop()
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Process incoming message and publish to MQTT.
        """
        if not MQTT_AVAILABLE:
            return
        
        if not self.client or not self._connected:
            self.report_error("Not connected to broker")
            return
        
        topic = self.config.get('topic', 'test/topic')
        
        # Allow msg.topic to override configured topic
        if 'topic' in msg and msg['topic']:
            topic = msg['topic']
        
        # Validate topic
        if not topic or topic.strip() == '':
            self.report_error("Topic is empty. Configure a topic in node properties.")
            return
        
        qos = int(self.config.get('qos', '0'))
        retain = self.config.get('retain', 'false') == 'true'
        
        # Get payload
        payload = msg.get('payload', '')
        
        # Serialize payload based on type
        if isinstance(payload, (dict, list)):
            # Convert structured data to JSON
            import json
            payload = json.dumps(payload)
        elif not isinstance(payload, (str, bytes)):
            payload = str(payload)
        
        try:
            result = self.client.publish(topic, payload, qos=qos, retain=retain)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                self.report_error(f"Publish failed to {topic} with code {result.rc}")
        except Exception as e:
            self.report_error(f"Error publishing to '{topic}': {e}")
