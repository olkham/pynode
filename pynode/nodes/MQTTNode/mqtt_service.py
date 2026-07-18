"""
MQTT Service Manager - handles shared MQTT connections across nodes.
Similar to Node-RED's configuration nodes concept.
"""

import logging
import os
import threading
import json
import uuid
from typing import Any, Dict, Callable, Optional, Set, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


class MQTTService:
    """
    Represents a single MQTT broker connection that can be shared across nodes.
    """
    
    def __init__(self, service_id: str, config: Dict[str, Any]):
        self.id = service_id
        self.name = config.get('name', 'MQTT Broker')
        self.broker = config.get('broker', 'localhost')
        self.port = int(config.get('port', 1883))
        self.username = config.get('username', '')
        self.password = config.get('password', '')
        self.client_id = config.get('clientId', '') or f"pynode_{service_id[:8]}"
        self.keep_alive = int(config.get('keepAlive', 60))
        self.clean_session = config.get('cleanSession', True)
        
        self.client: Optional[mqtt.Client] = None
        self._connected = False
        self._lock = threading.Lock()
        self._subscribers: Dict[str, Set[Callable]] = {}  # topic -> set of callbacks
        self._publishers: Set[str] = set()  # node IDs that want to publish
        self._message_callbacks: Dict[str, Callable] = {}  # node_id -> callback
        self._error_callbacks: Dict[str, Callable] = {}  # node_id -> error callback
        self._ref_count = 0
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker."""
        if rc == 0:
            self._connected = True
            # Re-subscribe to all topics
            with self._lock:
                for topic in self._subscribers:
                    client.subscribe(topic)
        else:
            self._connected = False
            error_msg = f"Connection to {self.broker}:{self.port} failed with code {rc}"
            self._notify_error(error_msg)
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker."""
        self._connected = False
        if rc != 0:
            self._notify_error(f"Unexpected disconnection from {self.broker}:{self.port}")
    
    def _on_message(self, client, userdata, message):
        """Callback when message is received."""
        topic = message.topic
        
        # Find matching subscribers (including wildcards)
        with self._lock:
            callbacks_to_call = set()
            for sub_topic, callbacks in self._subscribers.items():
                if self._topic_matches(sub_topic, topic):
                    callbacks_to_call.update(callbacks)
        
        # Call all matching callbacks
        for callback in callbacks_to_call:
            try:
                callback(topic, message.payload)
            except Exception as e:
                logger.error(f"Error in MQTT message callback: {e}")
    
    def _topic_matches(self, pattern: str, topic: str) -> bool:
        """Check if a topic matches a subscription pattern (with wildcards)."""
        pattern_parts = pattern.split('/')
        topic_parts = topic.split('/')
        
        for i, pattern_part in enumerate(pattern_parts):
            if pattern_part == '#':
                return True
            if i >= len(topic_parts):
                return False
            if pattern_part != '+' and pattern_part != topic_parts[i]:
                return False
        
        return len(pattern_parts) == len(topic_parts)
    
    def _notify_error(self, error_msg: str):
        """Notify all registered error callbacks."""
        with self._lock:
            callbacks = list(self._error_callbacks.values())
        
        for callback in callbacks:
            try:
                callback(error_msg)
            except Exception as e:
                logger.error(f"Error in error callback: {e}")
    
    def connect(self) -> bool:
        """Connect to the MQTT broker."""
        if not MQTT_AVAILABLE:
            self._notify_error("paho-mqtt not installed. Install with: pip install paho-mqtt")
            return False
        
        error_msg = None
        with self._lock:
            if self.client and self._connected:
                return True
            
            try:
                self.client = mqtt.Client(client_id=self.client_id, clean_session=self.clean_session)
                self.client.on_connect = self._on_connect
                self.client.on_disconnect = self._on_disconnect
                self.client.on_message = self._on_message
                
                if self.username:
                    self.client.username_pw_set(self.username, self.password)
                
                self.client.connect(self.broker, self.port, self.keep_alive)
                self.client.loop_start()
                return True
                
            except Exception as e:
                error_msg = f"Failed to connect to {self.broker}:{self.port} - {e}"
        
        # Call _notify_error outside the lock to avoid deadlock
        if error_msg:
            self._notify_error(error_msg)
            return False
    
    def disconnect(self):
        """Disconnect from the MQTT broker."""
        with self._lock:
            if self.client:
                try:
                    self.client.loop_stop()
                    self.client.disconnect()
                except Exception:
                    pass
                self.client = None
                self._connected = False
    
    def subscribe(self, node_id: str, topic: str, qos: int, callback: Callable):
        """Subscribe a node to a topic."""
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = set()
                # Actually subscribe if connected
                if self.client and self._connected:
                    self.client.subscribe(topic, qos)
            
            self._subscribers[topic].add(callback)
            self._message_callbacks[node_id] = callback
    
    def unsubscribe(self, node_id: str, topic: str, callback: Callable):
        """Unsubscribe a node from a topic."""
        with self._lock:
            if topic in self._subscribers:
                self._subscribers[topic].discard(callback)
                if not self._subscribers[topic]:
                    del self._subscribers[topic]
                    # Actually unsubscribe if connected
                    if self.client and self._connected:
                        self.client.unsubscribe(topic)
            
            self._message_callbacks.pop(node_id, None)
    
    def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False) -> bool:
        """Publish a message to a topic."""
        if not self.client or not self._connected:
            return False
        
        try:
            # Serialize payload
            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload)
            elif not isinstance(payload, (str, bytes)):
                payload = str(payload)
            
            result = self.client.publish(topic, payload, qos=qos, retain=retain)
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            self._notify_error(f"Publish error: {e}")
            return False
    
    def register_node(self, node_id: str, error_callback: Optional[Callable] = None):
        """Register a node as using this service."""
        with self._lock:
            self._ref_count += 1
            if error_callback:
                self._error_callbacks[node_id] = error_callback
    
    def unregister_node(self, node_id: str):
        """Unregister a node from this service."""
        with self._lock:
            self._ref_count = max(0, self._ref_count - 1)
            self._error_callbacks.pop(node_id, None)
            self._message_callbacks.pop(node_id, None)
    
    @property
    def ref_count(self) -> int:
        return self._ref_count
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert service config to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'broker': self.broker,
            'port': self.port,
            'username': self.username,
            'password': self.password,
            'clientId': self.client_id,
            'keepAlive': self.keep_alive,
            'cleanSession': self.clean_session
        }


def _default_config_file() -> Path:
    """Default services file location (source checkout: workflows/services/)."""
    module_dir = Path(__file__).parent.parent.parent.parent
    return Path(os.path.join(module_dir, 'workflows', 'services', 'mqtt_services.json'))


class MQTTServiceManager:
    """
    Manager for all MQTT services.

    Handles creating, retrieving, and persisting service configurations. Each
    Flask app owns one manager (``app.extensions['mqtt_manager']``); the
    module-level ``mqtt_manager`` instance is the default used by the MQTT
    nodes and the default app. Tests build isolated instances by passing a
    ``config_file`` inside a tmp directory so the real services file is never
    touched.
    """

    def __init__(self, config_file: Optional[Any] = None):
        self._services: Dict[str, MQTTService] = {}
        self.config_file = Path(config_file) if config_file else _default_config_file()
        # Ensure the parent directory exists so saves succeed.
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_services()
    
    def _load_services(self):
        """Load saved service configurations from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    for service_config in data.get('services', []):
                        service_id = service_config.get('id')
                        if service_id:
                            self._services[service_id] = MQTTService(service_id, service_config)
            except Exception as e:
                logger.error(f"Error loading MQTT services: {e}")
    
    def _save_services(self):
        """Save service configurations to file."""
        try:
            data = {
                'services': [s.to_dict() for s in self._services.values()]
            }
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving MQTT services: {e}")
    
    def get_service(self, service_id: str) -> Optional[MQTTService]:
        """Get a service by ID."""
        return self._services.get(service_id)
    
    def create_service(self, config: Dict[str, Any]) -> MQTTService:
        """Create a new MQTT service."""
        service_id = config.get('id') or str(uuid.uuid4())[:8]
        
        service = MQTTService(service_id, config)
        self._services[service_id] = service
        self._save_services()
        
        return service
    
    def update_service(self, service_id: str, config: Dict[str, Any]) -> Optional[MQTTService]:
        """Update an existing service configuration."""
        if service_id not in self._services:
            return None
        
        old_service = self._services[service_id]
        was_connected = old_service.connected
        
        # Disconnect old service
        old_service.disconnect()
        
        # Create new service with updated config
        config['id'] = service_id
        new_service = MQTTService(service_id, config)
        self._services[service_id] = new_service
        
        # Reconnect if was connected
        if was_connected:
            new_service.connect()
        
        self._save_services()
        return new_service
    
    def delete_service(self, service_id: str) -> bool:
        """Delete a service."""
        if service_id not in self._services:
            return False
        
        service = self._services[service_id]
        if service.ref_count > 0:
            return False  # Can't delete while in use
        
        service.disconnect()
        del self._services[service_id]
        self._save_services()
        return True
    
    def list_services(self) -> list:
        """List all available services."""
        return [
            {
                'id': s.id,
                'name': s.name,
                'broker': s.broker,
                'port': s.port,
                'connected': s.connected,
                'refCount': s.ref_count
            }
            for s in self._services.values()
        ]
    
    def start_all(self):
        """Connect all services that have registered nodes."""
        for service in self._services.values():
            if service.ref_count > 0:
                service.connect()
    
    def stop_all(self):
        """Disconnect all services."""
        for service in self._services.values():
            service.disconnect()


def test_connection(config: Dict[str, Any], timeout: float = 4.0) -> Tuple[bool, Optional[str]]:
    """Attempt an MQTT connection using the SUBMITTED config values.

    Uses a throwaway paho client so it never touches or disturbs any live or
    persisted service. The temporary client is always torn down
    (loop_stop/disconnect) in the finally block.

    Returns ``(success, error)`` where ``error`` is ``None`` on success and a
    human-readable message on failure. Never logs credentials.
    """
    if not MQTT_AVAILABLE:
        return False, "paho-mqtt is not installed. Install with: pip install paho-mqtt"

    broker = (config.get('broker') or 'localhost')
    try:
        port = int(config.get('port', 1883))
    except (TypeError, ValueError):
        return False, "Port must be a number"
    try:
        keep_alive = int(config.get('keepAlive', 60))
    except (TypeError, ValueError):
        keep_alive = 60
    username = config.get('username', '')
    password = config.get('password', '')
    clean_session = config.get('cleanSession', True)
    if isinstance(clean_session, str):
        clean_session = clean_session.strip().lower() != 'false'
    client_id = config.get('clientId', '') or f"pynode_test_{uuid.uuid4().hex[:8]}"

    result: Dict[str, Any] = {'rc': None}
    connected_event = threading.Event()

    def _on_connect(client, userdata, flags, rc):
        result['rc'] = rc
        connected_event.set()

    client = mqtt.Client(client_id=client_id, clean_session=bool(clean_session))
    client.on_connect = _on_connect
    if username:
        client.username_pw_set(username, password)

    try:
        # connect() performs a synchronous socket connect, so an unroutable
        # host / closed port raises here immediately (fast failure path).
        client.connect(broker, port, keepalive=keep_alive)
        client.loop_start()
        if not connected_event.wait(timeout):
            return False, f"Timed out connecting to {broker}:{port} after {timeout:.0f}s"
        rc = result['rc']
        if rc == 0:
            return True, None
        try:
            reason = mqtt.connack_string(rc)
        except Exception:
            reason = f"code {rc}"
        return False, f"Broker refused connection: {reason}"
    except Exception as e:
        return False, f"Could not connect to {broker}:{port} - {e}"
    finally:
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass


# Default module-level instance used by the MQTT nodes and the default app.
mqtt_manager = MQTTServiceManager()
