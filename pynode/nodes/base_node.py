"""
Base Node class for the Python Node-RED-like system.
All custom nodes should inherit from this class.

Message ownership contract (READ THIS BEFORE CHANGING A NODE)
------------------------------------------------------------
``BaseNode.send()`` has a **single-recipient fast path**: when a ``send()`` call
delivers to exactly one recipient, that recipient receives a *shallow* copy of
``msg`` (a fresh top-level dict that shares the payload and every nested object
with the sender's message - no ``deepcopy``). This makes forwarding a raw video
frame (a ~6 MB numpy array) essentially free instead of copying it per hop.

The rule that makes this safe:

    **After calling ``self.send(msg)`` a node MUST NOT read or mutate ``msg`` or
    anything reachable from it (its ``payload``, numpy arrays, nested dicts,
    ...). Prepare/mutate the message BEFORE ``send()``; treat it as handed off
    afterwards.**

Consequences a node author must respect:

* Don't do ``for x in xs: msg['payload'] = x; self.send(msg)`` - the first
  recipient sees the payload you overwrite on the next iteration. Build a fresh
  message per iteration (``self.create_message(...)`` or ``dict(msg)`` with a
  fresh payload).
* Don't send the *same* dict object to more than one output
  (``self.send(msg, 0); self.send(msg, 1)``) - both recipients would alias one
  payload. Copy for the second and later sends.
* Source nodes must not reuse a numpy buffer they already sent (e.g. an SDK
  buffer pool, or ``cap.read(preallocated)``). ``cap.read()`` with no argument
  allocates a fresh array each call, which is fine.

Fan-out is still safe automatically: when a single ``send()`` call has **more
than one** actual recipient, every recipient gets a full ``deepcopy`` (branches
never alias). Only the exactly-one-recipient case shares.

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

    def get_storage_dir(self, subdir: Optional[str] = None) -> str:
        """Return this node type's managed storage directory, creating it.

        Project rule: nodes must write any downloaded or generated binaries
        ONLY inside this per-node-type storage directory (or, for shared model
        weights, the shared models dir from ``pynode.config.resolve_models_dir``).
        Never scatter files into the process CWD — a pip-installed PyNode may be
        launched from a read-only or arbitrary directory.

        The path is ``<data_dir>/node_storage/<NodeType>/`` (``NodeType`` being
        ``self.type``), with ``subdir`` appended when given. The data dir is
        resolved via :func:`pynode.config.resolve_data_dir` at call time (not
        cached at import), so it honors the ``--data-dir`` flag / env var. The
        directory is created lazily on each call (``os.makedirs`` with
        ``exist_ok=True``).

        Args:
            subdir: Optional subdirectory to append (created too).

        Returns:
            Absolute path to the (now existing) storage directory.
        """
        import os
        from pynode import config

        storage_dir = os.path.join(config.resolve_data_dir(), 'node_storage',
                                   self.type)
        if subdir:
            storage_dir = os.path.join(storage_dir, subdir)
        os.makedirs(storage_dir, exist_ok=True)
        return storage_dir

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

    def _prepare_outgoing(self, msg: Dict[str, Any], deep: bool,
                          with_drop_count: bool) -> Dict[str, Any]:
        """Build the per-recipient outgoing message and stamp its metadata.

        Args:
            msg: The source message.
            deep: ``True`` -> full ``deepcopy`` (fan-out: isolate every
                recipient). ``False`` -> shallow copy: a NEW top-level dict
                (``dict(msg)``) that shares the payload and every nested object
                with ``msg``. The shallow form is only used for the
                single-recipient fast path, and is safe only because callers of
                ``send()`` promise not to touch ``msg`` afterwards (see the
                module docstring). Stamping metadata on the new top-level dict
                keeps the sender's own ``msg`` free of emit metadata; only the
                nested objects are shared.
            with_drop_count: Whether to stamp ``drop_count`` (queued path does,
                the direct-sink path historically does not).

        Metadata is stamped and then ``sort_msg_keys`` rebuilds the dict
        (underscore keys first), matching the historical ordering exactly.
        """
        out = copy.deepcopy(msg) if deep else dict(msg)
        emit = time()
        out[MessageKeys.TIMESTAMP_EMIT] = emit
        out[MessageKeys.AGE] = emit - out.get(MessageKeys.TIMESTAMP_ORIG, emit)
        if with_drop_count:
            # How many messages THIS node dropped before sending this one.
            out[MessageKeys.DROP_COUNT] = self.drop_count
        out[MessageKeys.QUEUE_LENGTH] = self._message_queue.qsize()
        return sort_msg_keys(out)

    def send(self, msg: Dict[str, Any], output_index: int = 0):
        """
        Send a message to connected nodes (non-blocking).
        Messages are queued and processed asynchronously.

        Copy semantics (hot path):

        * When exactly ONE recipient will actually receive this call, that
          recipient gets a SHALLOW copy - a fresh top-level dict that shares the
          payload and nested objects with ``msg`` (no ``deepcopy``). This avoids
          copying large payloads (e.g. raw video frames) on every hop.
        * When more than one recipient will receive, every recipient gets a full
          ``deepcopy`` so branches never alias each other.

        Recipient count is computed per call: disabled targets, and queued
        targets dropped by ``drop_while_busy``, do not count.

        CONTRACT: after calling ``send(msg)`` the sending node MUST NOT read or
        mutate ``msg`` or anything reachable from it (payload, arrays, nested
        dicts). Mutate the message BEFORE ``send()``. See the module docstring
        for the full rationale and the patterns to avoid.

        Args:
            msg: Message dictionary (must have 'payload' and 'topic')
            output_index: Which output port to send from (default 0)
        """
        if not self.enabled:
            return

        connections = self.outputs.get(output_index)
        if not connections:
            return

        # Pass 1: determine which targets will ACTUALLY receive. A disabled
        # target, or a queued target dropped by drop_while_busy, does not count
        # towards the recipient total that decides shallow-vs-deep.
        # Entries are (target_node, target_input, is_direct).
        recipients: List[Tuple['BaseNode', int, bool]] = []
        for target_node, target_input in connections:
            if not target_node.enabled:
                continue

            # Sink nodes (no outputs) with on_input_direct are delivered
            # synchronously and never dropped.
            if target_node.output_count == 0 and hasattr(target_node, 'on_input_direct'):
                recipients.append((target_node, target_input, True))
                continue

            # Queued path: drop if the target is busy or has a backlog
            # (checked before any expensive copy).
            if target_node.drop_while_busy and (
                    target_node._processing or not target_node._message_queue.empty()):
                target_node.drop_count += 1
                continue

            recipients.append((target_node, target_input, False))

        if not recipients:
            return

        # Fast path iff a single recipient will receive; any fan-out deep-copies.
        deep = len(recipients) > 1

        for target_node, target_input, is_direct in recipients:
            if is_direct:
                msg_to_send = self._prepare_outgoing(msg, deep, with_drop_count=False)
                try:
                    target_node.on_input_direct(msg_to_send, target_input)
                except Exception as e:
                    target_node.report_error(f"Error in direct processing: {e}")
            else:
                msg_to_send = self._prepare_outgoing(msg, deep, with_drop_count=True)
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
