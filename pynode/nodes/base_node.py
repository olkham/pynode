"""
Base Node class for the Python Node-RED-like system.
All custom nodes should inherit from this class.
"""

from dataclasses import dataclass
from time import time
import uuid
import queue
import threading
import base64
import copy
import html
from functools import wraps
from typing import Dict, List, Any, Optional, Tuple, Callable
import numpy as np
import cv2



def sort_msg_keys(msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sort message dict with underscore keys first, then alphabetically.
    Useful for displaying debug messages with metadata fields first.
    
    Args:
        msg: Message dictionary to sort
        
    Returns:
        New dictionary with sorted keys
    """
    return dict(sorted(msg.items(), key=lambda x: (not x[0].startswith('_'), x[0])))


class Info:
    """
    Helper class for building node information/help content.
    Provides a simple Python interface instead of writing raw HTML.
    
    Usage:
        info = Info()
        info.add_text("Description of the node.")
        info.add_header("Inputs")
        info.add_bullet("Input 0:", "Description of input 0")
        info.add_bullet("Input 1:", "Description of input 1")
        info.add_header("Example")
        info.add_code("Node1 → Node2").add_text("with some explanation")
    
    The class automatically escapes text to prevent HTML injection.
    """
    
    def __init__(self):
        self._content: List[str] = []
        self._inline_buffer: List[str] = []
    
    def _escape(self, text: str) -> str:
        """Escape HTML special characters for security."""
        return html.escape(str(text))
    
    def _flush_inline(self):
        """Flush any inline content to a paragraph."""
        if self._inline_buffer:
            self._content.append(f'<p>{"".join(self._inline_buffer)}</p>')
            self._inline_buffer = []
    
    def add_text(self, text: str) -> 'Info':
        """Add a paragraph of text."""
        self._flush_inline()
        self._content.append(f'<p>{self._escape(text)}</p>')
        return self
    
    def add_header(self, text: str) -> 'Info':
        """Add a section header."""
        self._flush_inline()
        self._content.append(f'<h4>{self._escape(text)}</h4>')
        return self
    
    def add_bullet(self, label: str, text: str = '') -> 'Info':
        """
        Add a bullet point. If label and text provided, label is bold.
        Use add_bullets() to add multiple bullets as a list.
        """
        self._flush_inline()
        if text:
            self._content.append(f'<ul><li><strong>{self._escape(label)}</strong> {self._escape(text)}</li></ul>')
        else:
            self._content.append(f'<ul><li>{self._escape(label)}</li></ul>')
        return self
    
    def add_bullets(self, *items: Tuple[str, str]) -> 'Info':
        """
        Add multiple bullet points as a single list.
        Each item can be a string or a tuple of (label, text).
        
        Example:
            info.add_bullets(
                ("Input 0:", "Background image"),
                ("Input 1:", "Foreground image"),
            )
        """
        self._flush_inline()
        bullets = []
        for item in items:
            if isinstance(item, tuple) and len(item) == 2:
                label, text = item
                bullets.append(f'<li><strong>{self._escape(label)}</strong> {self._escape(text)}</li>')
            else:
                bullets.append(f'<li>{self._escape(str(item))}</li>')
        self._content.append(f'<ul>{"".join(bullets)}</ul>')
        return self
    
    def add_code(self, code: str) -> 'Info':
        """Add inline code. Can be chained with text() for same line."""
        self._inline_buffer.append(f'<code>{self._escape(code)}</code>')
        return self
    
    def text(self, text: str) -> 'Info':
        """Add inline text (for chaining with code on same line)."""
        self._inline_buffer.append(f' {self._escape(text)}')
        return self
    
    def end(self) -> 'Info':
        """End the current inline sequence and flush to paragraph."""
        self._flush_inline()
        return self
    
    def __str__(self) -> str:
        """Convert to HTML string."""
        self._flush_inline()
        return ''.join(self._content)
    
    def __repr__(self) -> str:
        return f'Info({len(self._content)} elements)'

#Message key definitions to standardize message strings across all nodes
@dataclass(frozen=True)
class MessageKeys:

    # Image-specific keys
    @dataclass(frozen=True)
    class IMAGE:
        PATH: str = 'image'
        FORMAT: str = 'format'
        ENCODING: str = 'encoding'
        DATA: str = 'data'
        WIDTH: str = 'width'
        HEIGHT: str = 'height'
        JPEG_QUALITY: str = 'jpeg_quality'
        ENCODE_JPEG: str = 'encode_jpeg'

    # Camera-specific keys
    @dataclass(frozen=True)
    class CAMERA:
        DEVICE_INDEX: str = 'device_index'
        SOURCE: str = 'source'
        SOURCE_TYPE: str = 'source_type'
        FPS: str = 'fps'
        WIDTH: str = 'width'
        HEIGHT: str = 'height'
        JPEG_QUALITY: str = 'jpeg_quality'
        ENCODE_JPEG: str = 'encode_jpeg'

    # Message-level keys
    MSG_ID: str = '_msgid'
    TIMESTAMP_ORIG: str = '_timestamp_orig'
    TIMESTAMP_EMIT: str = '_timestamp_emit'
    AGE: str = '_age'
    DROP_COUNT: str = 'drop_count'
    DROP_MESSAGES: str = 'drop_messages'
    PAYLOAD: str = 'payload'
    TOPIC: str = 'topic'


def process_image(payload_path: str = MessageKeys.PAYLOAD, output_path: Optional[str] = None):
    """
    Decorator for image processing node methods.
    Automatically handles image decoding/encoding and error handling.
    
    This decorator:
    1. Extracts the image from msg using payload_path
    2. Decodes it to a numpy array
    3. Calls the decorated function with (self, image, msg, input_index)
    4. Encodes the result back to original format
    5. Places result at output_path (or payload_path.image if not specified)
    6. Sends the message
    
    The decorated function should return:
    - numpy array: The processed image
    - tuple (numpy array, dict): Image and additional msg fields to merge
    - None: Skip sending (function handles send itself)
    
    Args:
        payload_path: Dot-notation path to image in msg (default: 'payload')
        output_path: Dot-notation path for output image (default: payload_path + '.image' or 'payload.image')
    
    Example:
        @process_image(payload_path='payload')
        def process(self, image, msg, input_index):
            # image is already decoded as numpy array
            result = cv2.GaussianBlur(image, (5, 5), 0)
            return result  # Will be auto-encoded and sent
            
        @process_image(payload_path='payload')
        def process(self, image, msg, input_index):
            result = cv2.GaussianBlur(image, (5, 5), 0)
            return result, {'blur_applied': True}  # Adds extra field to msg
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, msg: Dict[str, Any], input_index: int = 0):
            # Check for payload
            if MessageKeys.PAYLOAD not in msg:
                self.send(msg)
                return
            
            # Get the image data from the specified path
            image_data = msg
            path_parts = payload_path.split('.')
            for part in path_parts:
                if isinstance(image_data, dict) and part in image_data:
                    image_data = image_data[part]
                else:
                    # Path not found, pass through
                    self.send(msg)
                    return
            
            # Decode image
            image, format_type = self.decode_image(image_data)
            if image is None:
                self.send(msg)
                return
            
            # Call the processing function
            try:
                result = func(self, image, msg, input_index)
            except Exception as e:
                self.report_error(f"Image processing error: {e}")
                return
            
            # Handle different return types
            if result is None:
                # Function handled send itself
                return
            
            extra_fields: Dict[str, Any] = {}
            result_image: np.ndarray | None = None  # Explicit type hint

            if isinstance(result, tuple):
                result_image, extra_fields = result
            else:
                result_image = result
            
            # Encode and place in output path
            if result_image is not None and isinstance(result_image, np.ndarray):
                encoded = self.encode_image(result_image, format_type)
                
                # Determine output path
                out_path = output_path
                if out_path is None:
                    # Default: if payload_path is 'payload', use 'payload.image'
                    # Otherwise use payload_path + '.image'
                    if payload_path == MessageKeys.PAYLOAD:
                        out_path = f"{MessageKeys.PAYLOAD}.{MessageKeys.IMAGE.PATH}"
                    else:
                        out_path = payload_path
                
                # Navigate to output location and set value
                out_parts = out_path.split('.')
                target = msg
                for part in out_parts[:-1]:
                    if part not in target or not isinstance(target[part], dict):
                        target[part] = {}
                    target = target[part]
                target[out_parts[-1]] = encoded
            
            # Merge extra fields into msg
            if extra_fields:
                msg.update(extra_fields)
            
            self.send(msg)
        
        return wrapper
    return decorator



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
    
    def create_message(self, payload: Any = None, topic: str = "", **kwargs) -> Dict[str, Any]:
        """
        Create a message in Node-RED format.
        
        Args:
            payload: The message payload (any type, optional)
            topic: Optional topic string
            **kwargs: Additional message properties
            
        Returns:
            Message dictionary with _msgid, _timestamp, and optional payload/topic
        """
        msg = {
            MessageKeys.MSG_ID: str(uuid.uuid4()),
            MessageKeys.TIMESTAMP_ORIG: time()
        }

        # Only include payload if explicitly provided (even if None was passed explicitly)
        if MessageKeys.PAYLOAD in kwargs:
            msg[MessageKeys.PAYLOAD] = kwargs.pop(MessageKeys.PAYLOAD)
        elif payload is not None:
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
                        msg_to_send = sort_msg_keys(msg_to_send)

                        # Add this node's drop count to message for monitoring
                        # (how many messages THIS node dropped before sending this one)
                        msg_to_send[MessageKeys.DROP_COUNT] = self.drop_count

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
    
    # Image processing helper methods
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
        # if not _HAS_CV2:
        #     return None, None
        
        try:
            # Handle nested payload.image structure
            if isinstance(payload, dict) and MessageKeys.IMAGE.PATH in payload:
                payload = payload[MessageKeys.IMAGE.PATH]
            
            # Direct numpy array
            if isinstance(payload, np.ndarray):
                return payload, 'numpy_array'
            
            # Camera node format: dict with 'format', 'encoding', 'data'
            if isinstance(payload, dict):
                img_format = payload.get('format')
                encoding = payload.get('encoding')
                data = payload.get('data')
                
                if img_format == 'bgr' and encoding == 'numpy':
                    # Direct numpy array in dict
                    if isinstance(data, np.ndarray):
                        return data, 'bgr_numpy_dict'
                    self.report_error("Expected numpy array in bgr/numpy dict format")
                    return None, None
                    
                elif img_format == 'jpeg' and encoding == 'base64':
                    # Base64 JPEG
                    img_bytes = base64.b64decode(data) # type: ignore
                    nparr = np.frombuffer(img_bytes, np.uint8)
                    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    return image, 'jpeg_base64_dict'
                    
                elif img_format == 'bgr' and encoding == 'raw':
                    # Raw list format
                    image = np.array(data, dtype=np.uint8)
                    return image, 'bgr_raw_dict'
                
                self.report_error(f"Unknown image dict format: {img_format}/{encoding}")
                return None, None
            
            # Direct base64 string
            if isinstance(payload, str):
                # Remove data URL prefix if present
                if payload.startswith('data:image'):
                    payload = payload.split(',')[1]
                
                img_bytes = base64.b64decode(payload)
                nparr = np.frombuffer(img_bytes, np.uint8)
                image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                return image, 'base64_string'
            
            self.report_error(f"Unsupported image payload type: {type(payload).__name__}")
            return None, None
            
        except Exception as e:
            self.report_error(f"Failed to decode image: {e}")
            return None, None
    
    def encode_image(self, image: Any, format_type: str) -> Any:
        """
        Encode numpy array image back to the original format.
        
        Args:
            image: Numpy array image
            format_type: Format identifier from decode_image()
            
        Returns:
            Encoded image in the specified format, or None on error
        """
        # if not _HAS_CV2:
        # #     return None
        
        try:
            if not isinstance(image, np.ndarray):
                self.report_error("Cannot encode: input is not a numpy array")
                return None
            
            if format_type == 'numpy_array':
                # Direct numpy array
                return image
                
            elif format_type == 'bgr_numpy_dict':
                # Dict with numpy array
                return {
                    'format': 'bgr',
                    'encoding': 'numpy',
                    'data': image,
                    'width': image.shape[1],
                    'height': image.shape[0]
                }
                
            elif format_type == 'jpeg_base64_dict':
                # JPEG base64 dict
                ret, buffer = cv2.imencode('.jpg', image)
                if ret:
                    jpeg_base64 = base64.b64encode(buffer.tobytes()).decode('utf-8')
                    return {
                        'format': 'jpeg',
                        'encoding': 'base64',
                        'data': jpeg_base64,
                        'width': image.shape[1],
                        'height': image.shape[0]
                    }
                self.report_error("Failed to encode image as JPEG base64 dict")
                return None
                
            elif format_type == 'bgr_raw_dict':
                # Raw list dict
                return {
                    'format': 'bgr',
                    'encoding': 'raw',
                    'data': image.tolist(),
                    'width': image.shape[1],
                    'height': image.shape[0]
                }
                
            elif format_type == 'base64_string':
                # Direct base64 string
                ret, buffer = cv2.imencode('.jpg', image)
                if ret:
                    return base64.b64encode(buffer.tobytes()).decode('utf-8')
                self.report_error("Failed to encode image as base64 string")
                return None
            
            self.report_error(f"Unknown image format type: {format_type}")
            return None
            
        except Exception as e:
            self.report_error(f"Failed to encode image: {e}")
            return None
    
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
            'config': self.config,
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
