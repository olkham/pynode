"""
MQTT In node - subscribes to MQTT topics and receives messages.
"""

import threading
from typing import Any, Dict
from base_node import BaseNode

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


class MqttInNode(BaseNode):
    """
    MQTT In node - subscribes to MQTT topics and receives messages.
    """
    display_name = 'MQTT In'
    icon = '📥'
    category = 'network'
    color = '#87A980'
    border_color = '#5F7858'
    text_color = '#000000'
    input_count = 0
    output_count = 1
    
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
            'default': '0'
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
            'clientId': '',
            'username': '',
            'password': ''
        })
    
    def on_message(self, client, userdata, message):
        """Callback when message is received."""
        try:
            payload = message.payload.decode('utf-8')
            # Try to parse as JSON for structured data
            import json
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                # Not JSON, keep as string
                pass
        except:
            payload = message.payload
        
        msg = self.create_message(
            payload=payload,
            topic=message.topic
        )
        self.send(msg)
    
    def on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker."""
        if rc == 0:
            self._connected = True
            topic = self.config.get('topic', 'test/topic')
            qos = int(self.config.get('qos', '0'))
            client.subscribe(topic, qos)
        else:
            self.report_error(f"Connection failed with code {rc}")
    
    def on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker."""
        self._connected = False
        if rc != 0:
            self.report_error("Unexpected disconnection from broker")
    
    def on_start(self):
        """Connect to MQTT broker when workflow starts."""
        super().on_start()  # Start base node worker thread
        
        if not MQTT_AVAILABLE:
            self.report_error("paho-mqtt not installed. Install with: pip install paho-mqtt")
            return
        
        broker = self.config.get('broker', 'localhost')
        port = int(self.config.get('port', '1883'))
        client_id = self.config.get('clientId', '') or f"pynode_in_{self.id[:8]}"
        username = self.config.get('username', '')
        password = self.config.get('password', '')
        
        try:
            self.client = mqtt.Client(client_id=client_id)
            self.client.on_connect = self.on_connect
            self.client.on_message = self.on_message
            self.client.on_disconnect = self.on_disconnect
            
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
