"""
Base Node class for the Python Node-RED-like system.
All custom nodes should inherit from this class.

``Info``, ``MessageKeys``/``sort_msg_keys`` and the image helpers
(``process_image``, plus the functions behind ``BaseNode.decode_image`` /
``BaseNode.encode_image``) live in ``pynode.nodes.info``,
``pynode.nodes.messages`` and ``pynode.nodes.image_utils`` respectively, and
are re-exported here so existing imports keep working::

    from pynode.nodes.base_node import BaseNode, Info, MessageKeys, \
        process_image, sort_msg_keys
"""

from time import time
import uuid
import queue
import threading
import copy
from typing import Dict, List, Any, Optional, Tuple

from pynode.nodes import image_utils
from pynode.nodes.image_utils import process_image  # noqa: F401 (re-export)
from pynode.nodes.info import Info  # noqa: F401 (re-export)
from pynode.nodes.messages import MessageKeys, sort_msg_keys

# Sentinel so create_message() can distinguish "payload not given" from an
# explicitly-passed payload=None (which must be included in the message).
_UNSET = object()


class BaseNode:
    """
    Base class for all nodes in the workflow system.
    Messages follow Node-RED structure with 'payload' and 'topic' fields.

    Subclasses can define a DEFAULT_CONFIG class attribute which will be
    automatically applied during initialization. This eliminates the need
    to manually call self.configure(self.DEFAULT_CONFIG) in __init__.
    """

    # Visual properties (can be overridden by subclasses)
    display_name = 'Base Node'  # Display name (without 'Node' suffix)
    icon = '◆'  # Icon character or emoji
    category = 'custom'
    color = '#2d2d30'
    border_color = '#555'
    text_color = '#d4d4d4'
    input_count = 1  # Number of input ports (0 for input-only nodes)
    output_count = 1  # Number of output ports (0 for output-only nodes)
    hidden = False  # If true, node is hidden from palette

    # Info text displayed in the Information panel when node is selected
    # Supports HTML for formatting
    info = ''

    # Default configuration - subclasses can override this
    # Will be auto-applied during __init__
    DEFAULT_CONFIG: Dict[str, Any] = {}

    # Property schema for the properties panel
    # Format: [{'name': 'propName', 'label': 'Display Label', 'type': 'text|textarea|select|button', 'options': [...], 'action': 'methodName'}]
    properties = [
        {
            'name': MessageKeys.DROP_MESSAGES,
            'label': 'Drop Messages When Busy',
            'type': 'checkbox',
            'default': True
        }
    ]

    # Action methods that may be triggered from the UI via
    # POST /api/nodes/<node_id>/<action>.
    # Only method names listed here can be invoked through that endpoint;
    # anything not declared (or starting with '_') returns 404.
    # These are the names referenced by 'action' keys in `properties` button/
    # toggle entries and in `ui_component_config`.
    # Format: ['method_name', ...]
    actions: List[str] = []

    # API routes that this node type exposes.
    # The server will register these as Flask routes at startup.
    # Nodes do NOT need to import Flask - the server handles request/response.
    # Format: [{'route': '/sub_path', 'methods': ['GET'], 'handler': 'method_name'}, ...]
    # The server creates /api/nodes/<node_id>/<route> for each entry.
    # Handler methods receive (request_data: dict) and return a result dict,
    # or just return a dict for GET requests with no input.
    # For file uploads, handler receives (file_storage, filename) parameters.
    api_routes: List[Dict[str, Any]] = []

    # SSE broadcast handlers for real-time UI updates.
    # The SSE broadcast worker calls these methods and pushes results to clients.
    # Format: [{'type': 'event_type', 'handler': 'method_name', 'throttle': None|seconds}, ...]
    # 'type' is the SSE event type sent to the client.
    # 'handler' is the method name to call on the node instance.
    # 'throttle' (optional): minimum interval in seconds between broadcasts (None = every cycle).
    sse_handlers: List[Dict[str, Any]] = []

    def __init__(self, node_id: Optional[str] = None, name: str = ""):
        """
        Initialize a base node.

        Args:
            node_id: Unique identifier for the node. Auto-generated if not provided.
            name: Human-readable name for the node.
        """
        self.id = node_id or str(uuid.uuid4())
        self.name = name or self.__class__.__name__
        self.type = self.__class__.__name__

        # Connections: output_index -> [(target_node, target_input_index), ...]
        self.outputs: Dict[int, List[tuple]] = {}

        # Configuration for the node
        self.config: Dict[str, Any] = {}

        # Initialize drop_while_busy to default (will be overridden by configure if needed)
        self.drop_while_busy = True
        self.drop_count = 0

        # Auto-apply DEFAULT_CONFIG if defined by subclass
        if self.DEFAULT_CONFIG:
            self.configure(self.DEFAULT_CONFIG)

        # Node state
        self.enabled = True

        # Non-blocking message queue
        self._message_queue = queue.Queue(maxsize=1000)  # Limit queue size to prevent memory issues
        self._worker_thread = None
        self._stop_worker_flag = False
        self._processing = False  # True when actively processing a message

        # Error handling
        self._workflow_engine = None  # Will be set by workflow engine

    def set_workflow_engine(self, engine):
        """Set reference to the workflow engine for error reporting."""
        self._workflow_engine = engine

    def report_error(self, error_msg: str):
        """
        Report an error to all ErrorNodes in the workflow.

        Args:
            error_msg: The error message to report
        """
        if self._workflow_engine:
            self._workflow_engine.broadcast_error(self.id, self.name, error_msg)

    def connect(self, target_node: 'BaseNode', output_index: int = 0, target_input_index: int = 0):
        """
        Connect this node's output to another node's input.

        Args:
            target_node: The node to connect to
            output_index: Which output port to use (default 0)
            target_input_index: Which input port on target (default 0)
        """
        if output_index not in self.outputs:
            self.outputs[output_index] = []

        self.outputs[output_index].append((target_node, target_input_index))

    def disconnect(self, target_node: 'BaseNode', output_index: int = 0):
        """
        Disconnect this node from a target node.

        Args:
            target_node: The node to disconnect from
            output_index: Which output port to disconnect
        """
        if output_index in self.outputs:
            self.outputs[output_index] = [
                (node, idx) for node, idx in self.outputs[output_index]
                if node.id != target_node.id
            ]

    def create_message(self, payload: Any = _UNSET, topic: str = "", **kwargs) -> Dict[str, Any]:
        """
        Create a message in Node-RED format.

        Args:
            payload: The message payload (any type, optional). Omitted from
                the message when not given; an explicitly-passed None IS
                included (payload=None -> {'payload': None, ...}).
            topic: Optional topic string
            **kwargs: Additional message properties

        Returns:
            Message dictionary with _msgid, _timestamp, and optional payload/topic
        """
        msg = {
            MessageKeys.MSG_ID: str(uuid.uuid4()),
            MessageKeys.TIMESTAMP_ORIG: time()
        }

        # Only include payload if explicitly provided (even if None was passed
        # explicitly). The _UNSET sentinel distinguishes create_message() from
        # create_message(payload=None).
        if payload is not _UNSET:
            msg[MessageKeys.PAYLOAD] = payload

        if topic:
            msg[MessageKeys.TOPIC] = topic

        msg.update(kwargs)
        return msg

    def send(self, msg: Dict[str, Any], output_index: int = 0):
        """
        Send a message to connected nodes (non-blocking).
        Messages are queued and processed asynchronously.
        Each recipient gets a deep copy to prevent cross-talk between branches
        and to prevent downstream modifications from affecting the sender.

        Args:
            msg: Message dictionary (must have 'payload' and 'topic')
            output_index: Which output port to send from (default 0)
        """
        if not self.enabled:
            return

        if output_index in self.outputs:
            connections = self.outputs[output_index]

            for target_node, target_input in connections:
                if target_node.enabled:
                    # Check if target node prefers direct processing (no outputs = sink node)
                    if target_node.output_count == 0 and hasattr(target_node, 'on_input_direct'):
                        # Deep copy for direct processing to prevent cross-talk
                        msg_to_send = copy.deepcopy(msg)
                        msg_to_send[MessageKeys.TIMESTAMP_EMIT] = time()
                        msg_to_send[MessageKeys.AGE] = (
                            msg_to_send[MessageKeys.TIMESTAMP_EMIT]
                            - msg_to_send.get(MessageKeys.TIMESTAMP_ORIG, msg_to_send[MessageKeys.TIMESTAMP_EMIT])
                        )
                        msg_to_send[MessageKeys.QUEUE_LENGTH] = self._message_queue.qsize()
                        msg_to_send = sort_msg_keys(msg_to_send)

                        try:
                            target_node.on_input_direct(msg_to_send, target_input)
                        except Exception as e:
                            target_node.report_error(f"Error in direct processing: {e}")
                    else:
                        # Check if target wants to drop messages when busy (before expensive copy)
                        # Drop if node is processing OR has queued messages
                        if target_node.drop_while_busy and (target_node._processing or not target_node._message_queue.empty()):
                            # Drop message instead of queuing
                            target_node.drop_count += 1
                            continue

                        # Deep copy message for each recipient to prevent cross-talk
                        msg_to_send = copy.deepcopy(msg)
                        msg_to_send[MessageKeys.TIMESTAMP_EMIT] = time()
                        msg_to_send[MessageKeys.AGE] = (
                            msg_to_send[MessageKeys.TIMESTAMP_EMIT]
                            - msg_to_send.get(MessageKeys.TIMESTAMP_ORIG, msg_to_send[MessageKeys.TIMESTAMP_EMIT])
                        )

                        # Add this node's drop count to message for monitoring
                        # (how many messages THIS node dropped before sending this one)
                        msg_to_send[MessageKeys.DROP_COUNT] = self.drop_count
                        msg_to_send[MessageKeys.QUEUE_LENGTH] = self._message_queue.qsize()

                        msg_to_send = sort_msg_keys(msg_to_send)

                        # Queue message for target node (non-blocking)
                        try:
                            target_node._message_queue.put_nowait((msg_to_send, target_input))
                        except queue.Full:
                            # Queue full - drop message or handle overflow
                            target_node.report_error("Message queue full, dropping message")

    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Called when this node receives a message.
        Override this method in subclasses to implement node logic.

        Args:
            msg: Message dictionary with 'payload', 'topic', etc.
            input_index: Which input port received the message
        """
        # Default behavior: pass through
        self.send(msg)

    def _start_worker(self):
        """
        Start the worker thread to process queued messages.
        """
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_worker_flag = False
            self._worker_thread = threading.Thread(target=self._process_messages, daemon=True)
            self._worker_thread.start()

    def _process_messages(self):
        """
        Worker thread that processes messages from the queue.
        Uses adaptive timeout to balance responsiveness with CPU usage.
        """
        idle_count = 0
        while not self._stop_worker_flag:
            try:
                # Adaptive timeout: faster when active, slower when idle
                timeout = 0.01 if idle_count < 10 else 0.1
                msg, input_index = self._message_queue.get(timeout=timeout)
                idle_count = 0  # Reset on successful message

                # Process the message
                self._processing = True
                try:
                    self.on_input(msg, input_index)
                except Exception as e:
                    self.report_error(f"Error processing message: {e}")
                finally:
                    self._processing = False
                    self._message_queue.task_done()

            except queue.Empty:
                # No message available, increase idle count
                idle_count += 1
                continue
            except Exception as e:
                self.report_error(f"Worker thread error: {e}")

    def on_start(self):
        """
        Called when the node is started/deployed.
        Override to implement initialization logic.
        """
        # Start message processing worker
        self._start_worker()

    def on_stop(self):
        """
        Called when the node is stopped.
        Override to implement cleanup logic.
        """
        # Stop message processing worker
        self._stop_worker_flag = True
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    def configure(self, config: Dict[str, Any]):
        """
        Configure the node with settings.

        Args:
            config: Configuration dictionary
        """
        self.config.update(config)
        # Update drop_while_busy flag from config
        # Handle both boolean and string values for compatibility
        self.drop_while_busy = self.get_config_bool(MessageKeys.DROP_MESSAGES, True)

    def get_config_bool(self, key: str, default: bool = False) -> bool:
        """
        Get a boolean configuration value, with support for string representations of booleans.

        Args:
            key: The configuration key
            default: Default value if the key is not present

        Returns:
            Boolean value of the configuration setting
        """
        val = self.config.get(key, default)
        return val.lower() in ('true', '1', 'yes') if isinstance(val, str) else bool(val)

    def get_config_int(self, key: str, default: int = 0) -> int:
        """
        Get an integer configuration value.

        Args:
            key: The configuration key
            default: Default value if the key is not present

        Returns:
            Integer value of the configuration setting
        """
        return int(self.config.get(key, default))

    def get_config_float(self, key: str, default: float = 0.0) -> float:
        """
        Get a float configuration value.

        Args:
            key: The configuration key
            default: Default value if the key is not present

        Returns:
            Float value of the configuration setting
        """
        return float(self.config.get(key, default))

    def _get_nested_value(self, obj: Dict, path: str) -> Any:
        """
        Get a value from a nested path using dot notation.
        Supports array indexing like 'items[0]' and optional 'msg.' prefix.

        Args:
            obj: The object to get the value from (usually a message dict)
            path: Dot-separated path string (e.g., 'payload.data', 'items[0].name')

        Returns:
            The value at the path, or None if not found

        Examples:
            self._get_nested_value(msg, 'payload')  # msg['payload']
            self._get_nested_value(msg, 'payload.data')  # msg['payload']['data']
            self._get_nested_value(msg, 'items[0].name')  # msg['items'][0]['name']
            self._get_nested_value(msg, 'msg.payload')  # msg['payload'] (msg. prefix stripped)
        """
        import re

        if not path:
            return None

        # Handle msg. prefix for compatibility
        if path.startswith('msg.'):
            path = path[4:]

        parts = path.split('.')
        current = obj

        for part in parts:
            if current is None:
                return None

            # Handle array indexing like 'items[0]'
            match = re.match(r'(\w+)\[(\d+)\]', part)
            if match:
                key, index = match.groups()
                if isinstance(current, dict) and key in current:
                    current = current[key]
                    if isinstance(current, (list, tuple)) and int(index) < len(current):
                        current = current[int(index)]
                    else:
                        return None
                else:
                    return None
            elif isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None

        return current

    def _set_nested_value(self, obj: Dict, path: str, value: Any) -> bool:
        """
        Set a value at a nested path like 'payload.image.width'
        Supports array indexing and msg. prefix handling.

        Args:
            obj: The object to set the value in
            path: Dot-separated path string
            value: The value to set

        Returns:
            True if successful, False otherwise
        """
        import re

        # Handle msg. prefix
        if path.startswith('msg.'):
            path = path[4:]

        parts = path.split('.')
        current = obj

        # Navigate to parent of target
        for part in parts[:-1]:
            # Handle array indexing
            match = re.match(r'(\w+)\[(\d+)\]', part)
            if match:
                key, index = match.groups()
                if key not in current:
                    current[key] = []
                current = current[key]
                index = int(index)
                while len(current) <= index:
                    current.append({})
                current = current[index]
            else:
                if part not in current:
                    current[part] = {}
                current = current[part]

        # Set the final value
        final_key = parts[-1]
        match = re.match(r'(\w+)\[(\d+)\]', final_key)
        if match:
            key, index = match.groups()
            if key not in current:
                current[key] = []
            while len(current[key]) <= int(index):
                current[key].append(None)
            current[key][int(index)] = value
        else:
            current[final_key] = value

        return True

    # Image processing helper methods (thin delegates; the implementations
    # live in pynode.nodes.image_utils and report failures through this
    # node's report_error).
    def decode_image(self, payload: Any) -> Tuple[Any, Optional[str]]:
        """
        Decode image from various formats into a numpy array.
        Returns (image, format_type) tuple where format_type indicates the input format.

        Supported formats:
        - Direct numpy array
        - Dict with 'format', 'encoding', 'data' (camera node format)
        - Direct base64 string

        Args:
            payload: Image payload in any supported format

        Returns:
            Tuple of (image as numpy array or None, format_identifier string or None)
        """
        return image_utils.decode_image(payload, report_error=self.report_error)

    def encode_image(self, image: Any, format_type: str) -> Any:
        """
        Encode numpy array image back to the original format.

        Args:
            image: Numpy array image
            format_type: Format identifier from decode_image()

        Returns:
            Encoded image in the specified format, or None on error
        """
        return image_utils.encode_image(image, format_type,
                                        report_error=self.report_error)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize node to dictionary for API/storage.

        Returns:
            Dictionary representation of the node
        """
        return {
            'id': self.id,
            'type': self.type,
            'name': self.name,
            # Shallow copy so callers can't mutate the node's config in place
            'config': dict(self.config),
            'enabled': self.enabled,
            'inputCount': self.input_count,
            'outputCount': self.output_count,
            'outputs': {
                str(idx): [(node.id, target_idx) for node, target_idx in connections]
                for idx, connections in self.outputs.items()
            }
        }

    def __repr__(self):
        return f"<{self.type}(id={self.id}, name={self.name})>"
