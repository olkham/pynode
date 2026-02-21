# Agent Guide: Creating New PyNode Nodes

This document provides complete instructions for AI agents (Claude, Copilot, etc.) to implement new nodes in the PyNode visual workflow system. Follow these instructions precisely.

## Quick Reference

To create a new node, create a folder under `pynode/nodes/` with these files:

```
pynode/nodes/YourNodeName/
├── __init__.py          # REQUIRED: exports node class
├── your_node_name.py    # REQUIRED: node implementation
└── requirements.txt     # RECOMMENDED: third-party dependencies (if any)
```

No other files need to be modified. Nodes are auto-discovered at startup.

---

## Step-by-Step Process

### 1. Create the Folder

Create a folder in `pynode/nodes/` using CamelCase naming that matches your node class name:

```
pynode/nodes/MyNewNode/
```

### 2. Create `__init__.py`

```python
from .my_new_node import MyNewNode

__all__ = ['MyNewNode']
```

Rules:
- Import must match your class name exactly
- Class name **must** end with `Node`
- The `.py` filename can be anything, but use snake_case by convention

### 3. Create the Node Implementation

Use this template as your starting point:

```python
"""
Brief description of what the node does.
"""

from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

# Build documentation using the Info helper
_info = Info()
_info.add_text("What this node does in one sentence.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Description of what this input expects.")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Description of what this output produces.")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Property Name:", "What it controls (default: value).")
)


class MyNewNode(BaseNode):
    """Docstring for the node."""

    # --- Visual appearance ---
    display_name = 'My New Node'
    icon = '🔧'
    category = 'function'          # See "Categories" section below
    color = '#FFA07A'              # Background color (hex)
    border_color = '#FF7F50'       # Border color (hex)
    text_color = '#000000'         # Text color (hex)

    # --- I/O ---
    input_count = 1
    output_count = 1

    # --- Documentation ---
    info = str(_info)

    # --- Default configuration ---
    DEFAULT_CONFIG = {
        'my_property': 'default_value',
        MessageKeys.DROP_MESSAGES: 'false'
    }

    # --- Property schema (generates UI form) ---
    properties = [
        {
            'name': 'my_property',
            'label': 'My Property',
            'type': 'text',
            'default': 'default_value',
            'help': 'What this property does'
        }
    ]

    def __init__(self, node_id=None, name="my new node"):
        super().__init__(node_id, name)
        # Initialize instance variables here

    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Process an incoming message."""
        # Read config
        my_prop = self.config.get('my_property', 'default_value')

        # Read payload
        payload = msg.get(MessageKeys.PAYLOAD)

        # Process
        result = payload  # your logic here

        # Send downstream
        msg[MessageKeys.PAYLOAD] = result
        self.send(msg)
```

### 4. Create `requirements.txt` (if the node uses third-party packages)

If your node imports any packages that are **not** part of the Python standard library and are **not** already in the project's root `requirements.txt`, create a `requirements.txt` in your node folder. The install script will automatically `pip install` these when the node is installed.

```
# pynode/nodes/MyNewNode/requirements.txt
requests>=2.28.0
beautifulsoup4>=4.11.0
```

Rules:
- **Always pin a minimum version** (e.g., `>=2.28.0`) to avoid compatibility surprises.
- **Only list direct dependencies** your node imports. Don't list transitive dependencies.
- **Don't duplicate** packages already in the project root `requirements.txt` (e.g., `numpy`, `opencv-python`, `torch`, `flask`, `paho-mqtt`, `ultralytics`, `supervision` are already project dependencies).
- If your node uses **only standard library and existing project dependencies**, you can skip this file.

---

## Categories

Use one of the existing categories so the node appears in the correct palette section:

| Category | Use for | Example nodes |
|----------|---------|---------------|
| `'common'` | Basic utility nodes | Inject, Debug |
| `'function'` | Data transformation | Filter, Split, Join, Change, Function |
| `'logic'` | Routing/control flow | Switch, Gate, Sync |
| `'input'` | Source nodes (no inputs) | Camera, FrameSource |
| `'output'` | Sink nodes (no outputs) | ImageViewer, VideoWriter |
| `'network'` | Network/communication | MQTT, Webhook, REST |
| `'vision'` | AI/ML vision | Inference, Tracker, CropNode |
| `'opencv'` | OpenCV image processing | Blur, Threshold, Resize |
| `'analysis'` | Metrics/measurement | BBoxMetrics, PolygonMetrics |
| `'node probes'` | Debugging/monitoring | Counter, RateProbe |

---

## Property Types

Properties define the configuration UI shown when a node is selected.

### Text Input
```python
{
    'name': 'field_name',
    'label': 'Display Label',
    'type': 'text',
    'default': 'default_value',
    'help': 'Tooltip text',
    'placeholder': 'Hint text'
}
```

### Number Input
```python
{
    'name': 'count',
    'label': 'Count',
    'type': 'number',
    'default': 10,
    'min': 0,
    'max': 100,
    'help': 'How many items'
}
```

### Select Dropdown
```python
{
    'name': 'mode',
    'label': 'Mode',
    'type': 'select',
    'options': [
        {'value': 'fast', 'label': 'Fast Mode'},
        {'value': 'accurate', 'label': 'Accurate Mode'}
    ],
    'default': 'fast',
    'help': 'Processing mode'
}
```

### Checkbox
```python
{
    'name': 'enabled',
    'label': 'Enable Feature',
    'type': 'checkbox',
    'default': True,
    'help': 'Toggle this feature'
}
```

### Textarea
```python
{
    'name': 'code',
    'label': 'Python Code',
    'type': 'textarea',
    'default': 'return msg'
}
```

### Button (triggers a method on the node)
```python
{
    'name': 'reset_btn',
    'label': 'Reset',
    'type': 'button',
    'action': 'reset_method'   # calls self.reset_method()
}
```

### File Upload
```python
{
    'name': 'model_path',
    'label': 'Model File',
    'type': 'file',
    'accept': '.pt,.onnx,.xml'
}
```

### Conditional Visibility (`showIf`)

Show a property only when another property has a specific value:

```python
# Show only when 'method' is 'gaussian'
{
    'name': 'sigma',
    'label': 'Sigma',
    'type': 'number',
    'default': 0,
    'showIf': {'method': 'gaussian'}
}

# Show when 'mode' is any of several values
{
    'name': 'delay',
    'label': 'Delay (ms)',
    'type': 'number',
    'showIf': {'mode': ['delay', 'delay_count']}
}

# Show when a checkbox is unchecked
{
    'name': 'width',
    'label': 'Width',
    'type': 'number',
    'showIf': {'use_auto_size': False}
}
```

---

## Accessing Configuration Values

Always use the typed helpers to avoid type errors from string-valued configs:

```python
def on_input(self, msg, input_index=0):
    text_val = self.config.get('field_name', 'default')          # string
    bool_val = self.get_config_bool('enabled', False)             # bool (handles 'true'/'false' strings)
    int_val  = self.get_config_int('count', 0)                    # int
    float_val = self.get_config_float('threshold', 0.5)           # float
```

---

## Message Structure

Messages are dictionaries following this structure:

```python
{
    'payload': Any,              # Main data - can be anything
    'topic': str,                # Optional topic string
    '_msgid': str,               # Auto-generated unique ID
    '_timestamp_orig': float,    # Original creation timestamp
    '_timestamp_emit': float,    # Emission timestamp
    '_age': float,               # Age in seconds
    '_queue_length': int,        # Queue depth when received
    # ... any additional custom fields
}
```

### Key MessageKeys Constants

Always use `MessageKeys` instead of hardcoded strings:

```python
MessageKeys.PAYLOAD              # 'payload'
MessageKeys.TOPIC                # 'topic'
MessageKeys.DROP_MESSAGES        # 'drop_messages'
MessageKeys.IMAGE.PATH           # 'image'
MessageKeys.IMAGE.FORMAT         # 'format'
MessageKeys.IMAGE.ENCODING       # 'encoding'
MessageKeys.IMAGE.DATA           # 'data'
MessageKeys.IMAGE.WIDTH          # 'width'
MessageKeys.IMAGE.HEIGHT         # 'height'
MessageKeys.CV.BBOX              # 'bbox'
MessageKeys.CV.DETECTIONS        # 'detections'
```

### Creating & Sending Messages

```python
# Modify and forward
msg[MessageKeys.PAYLOAD] = new_data
self.send(msg)

# Send to a specific output
self.send(msg, output_index=1)

# Create a brand new message
new_msg = self.create_message(payload={'key': 'value'}, topic='my/topic')
self.send(new_msg)
```

---

## Node Patterns

### Pattern 1: Transform Node (most common)

Receives a message, modifies it, sends it on.

```python
class UpperCaseNode(BaseNode):
    display_name = 'Upper Case'
    icon = 'Aa'
    category = 'function'
    color = '#C8E6C9'
    border_color = '#4CAF50'
    input_count = 1
    output_count = 1

    def on_input(self, msg, input_index=0):
        payload = msg.get(MessageKeys.PAYLOAD, '')
        msg[MessageKeys.PAYLOAD] = str(payload).upper()
        self.send(msg)
```

### Pattern 2: Source Node (no inputs, generates messages)

Uses a thread to produce messages. `input_count = 0`.

```python
import threading
import time

class TimerNode(BaseNode):
    display_name = 'Timer'
    icon = '⏱'
    category = 'input'
    input_count = 0
    output_count = 1

    DEFAULT_CONFIG = {'interval': 1}

    properties = [
        {'name': 'interval', 'label': 'Interval (s)', 'type': 'number', 'default': 1}
    ]

    def __init__(self, node_id=None, name="timer"):
        super().__init__(node_id, name)
        self.running = False
        self._thread = None

    def on_start(self):
        super().on_start()
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def on_stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        super().on_stop()

    def _loop(self):
        while self.running:
            interval = self.get_config_float('interval', 1.0)
            msg = self.create_message(payload=time.time(), topic='timer')
            self.send(msg)
            time.sleep(interval)
```

### Pattern 3: Sink Node (no outputs, consumes messages)

`output_count = 0`. Uses `on_input_direct()` instead of `on_input()` for direct processing without the queue.

```python
class LogNode(BaseNode):
    display_name = 'Log'
    icon = '📝'
    category = 'output'
    input_count = 1
    output_count = 0

    def on_input_direct(self, msg, input_index=0):
        """Called directly (not queued) for sink nodes."""
        print(f"[LOG] {msg.get(MessageKeys.PAYLOAD)}")
```

### Pattern 4: Router (multiple outputs)

Routes messages to different outputs based on conditions.

```python
class TypeRouterNode(BaseNode):
    display_name = 'Type Router'
    icon = '🔀'
    category = 'logic'
    input_count = 1
    output_count = 3  # string, number, other

    info = "Routes by payload type: output 0 = string, 1 = number, 2 = other"

    def on_input(self, msg, input_index=0):
        payload = msg.get(MessageKeys.PAYLOAD)
        if isinstance(payload, str):
            self.send(msg, output_index=0)
        elif isinstance(payload, (int, float)):
            self.send(msg, output_index=1)
        else:
            self.send(msg, output_index=2)
```

### Pattern 5: Multi-Input Node

Receives messages on different input ports.

```python
class MergeNode(BaseNode):
    display_name = 'Merge'
    icon = '🔗'
    category = 'function'
    input_count = 2
    output_count = 1

    def __init__(self, node_id=None, name="merge"):
        super().__init__(node_id, name)
        self._last = [None, None]

    def on_input(self, msg, input_index=0):
        self._last[input_index] = msg.get(MessageKeys.PAYLOAD)
        combined = {'input_0': self._last[0], 'input_1': self._last[1]}
        out = self.create_message(payload=combined)
        self.send(out)
```

### Pattern 6: Image Processing Node (OpenCV)

Use the `@process_image()` decorator to automatically decode/encode images.

```python
import cv2
import numpy as np
from pynode.nodes.base_node import BaseNode, process_image, Info, MessageKeys

class GrayscaleNode(BaseNode):
    display_name = 'Grayscale'
    icon = '🌑'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1

    @process_image()
    def on_input(self, image: np.ndarray, msg: dict, input_index: int = 0):
        """image is already decoded as a numpy array (BGR)."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return gray
        # The decorator re-encodes and sends automatically
```

The decorator handles:
- Decoding images from any supported format (numpy, base64 JPEG, dict)
- Placing the result back in the correct message path
- Encoding the result to match the original format
- Sending the message downstream

To pass extra fields alongside the image:
```python
@process_image()
def on_input(self, image, msg, input_index=0):
    result = cv2.flip(image, 1)
    return result, {'flipped': True}  # extra fields merged into payload
```

### Pattern 7: Dynamic Output Count

Adjust output count based on configuration.

```python
class DynamicSplitNode(BaseNode):
    display_name = 'Dynamic Split'
    input_count = 1
    output_count = 2

    DEFAULT_CONFIG = {'output_count': 2}
    properties = [
        {'name': 'output_count', 'label': 'Outputs', 'type': 'number', 'default': 2, 'min': 1, 'max': 10}
    ]

    def configure(self, config):
        super().configure(config)
        self.output_count = self.get_config_int('output_count', 2)
```

### Pattern 8: Dynamic Properties

Generate properties at runtime using a classmethod.

```python
class DeviceNode(BaseNode):
    display_name = 'Device'

    @classmethod
    def get_properties(cls):
        # Dynamically detect available devices
        devices = cls._scan_devices()
        return [
            {
                'name': 'device',
                'label': 'Device',
                'type': 'select',
                'options': [{'value': d, 'label': d} for d in devices]
            }
        ]

    properties = property(lambda self: self.get_properties())

    @classmethod
    def _scan_devices(cls):
        return ['cpu', 'cuda:0']  # example
```

---

## Lifecycle Methods

Override these as needed. **Always call the parent method.**

```python
def __init__(self, node_id=None, name="my node"):
    super().__init__(node_id, name)
    # Initialize instance variables

def on_start(self):
    """Called when the workflow is deployed/started."""
    super().on_start()  # Starts the worker thread
    # Open connections, start threads, allocate resources

def on_stop(self):
    """Called when the workflow is stopped."""
    # Close connections, stop threads, free resources
    super().on_stop()  # Stops the worker thread

def configure(self, config):
    """Called when configuration changes (from UI or API)."""
    super().configure(config)  # Merges config into self.config
    # React to config changes (e.g., update output_count)

def on_close(self):
    """Called when the node is deleted."""
    self.on_stop()
```

---

## Error Handling

Always wrap risky operations and report errors:

```python
def on_input(self, msg, input_index=0):
    try:
        result = risky_operation(msg.get(MessageKeys.PAYLOAD))
        msg[MessageKeys.PAYLOAD] = result
        self.send(msg)
    except Exception as e:
        self.report_error(f"Failed to process: {e}")
```

`report_error()` broadcasts the error to all ErrorNode instances in the workflow.

---

## Nested Value Access

Use built-in helpers for dot-notation paths into nested dicts/arrays:

```python
# msg = {'payload': {'results': [{'score': 0.95}]}}

value = self._get_nested_value(msg, 'payload.results[0].score')  # 0.95

self._set_nested_value(msg, 'payload.output.label', 'cat')
# msg['payload']['output']['label'] = 'cat'
```

---

## Info Documentation Builder

Use the `Info` class for rich HTML documentation displayed in the UI:

```python
_info = Info()
_info.add_text("Plain text description.")
_info.add_header("Section Title")
_info.add_bullet("Label:", "Description")
_info.add_bullets(
    ("Label 1:", "Description 1"),
    ("Label 2:", "Description 2")
)
_info.add_code("example_code()").text(" - explanation text").end()

class MyNode(BaseNode):
    info = str(_info)
```

---

## Hidden Nodes

To hide a node from the palette (e.g., system-internal nodes):

```python
class InternalNode(BaseNode):
    hidden = True
```

---

## Checklist Before Finishing

- [ ] Class name ends with `Node`
- [ ] `__init__.py` exports the class in `__all__`
- [ ] `super().__init__()` called in `__init__`
- [ ] `super().on_start()` / `super().on_stop()` called if overridden
- [ ] `super().configure()` called if overridden
- [ ] `MessageKeys` constants used instead of hardcoded strings
- [ ] Error handling with `self.report_error()` for risky operations
- [ ] `info` populated with `Info()` builder for documentation
- [ ] `DEFAULT_CONFIG` matches `properties` defaults
- [ ] Threads are started in `on_start()` and stopped in `on_stop()` (if applicable)
- [ ] Resources are cleaned up in `on_stop()`
- [ ] `requirements.txt` created in the node folder if third-party packages are imported

---

## Common Mistakes to Avoid

1. **Forgetting `super().__init__()`** - The base class sets up the message queue and worker thread.
2. **Forgetting `super().on_start()` / `super().on_stop()`** - The base class manages the worker thread.
3. **Modifying a message sent to multiple outputs** - Use `self.create_message()` or `copy.deepcopy()` for separate copies.
4. **Using hardcoded strings** - Use `MessageKeys.PAYLOAD` not `'payload'`, etc.
5. **Not handling `None` payloads** - Always provide defaults: `msg.get(MessageKeys.PAYLOAD, default)`.
6. **Blocking in `on_input`** - Long operations block the worker thread. For CPU-bound work, consider additional threads.
7. **Putting the class in the wrong folder** - The folder must be directly under `pynode/nodes/`, not nested deeper.
8. **Class name not ending in `Node`** - Auto-discovery filters by this suffix.
9. **Circular imports** - Only import from `pynode.nodes.base_node`. Don't import other node types.
10. **Forgetting to send** - If you don't call `self.send(msg)`, the message is silently dropped (this is valid for filters, but a common bug otherwise).
