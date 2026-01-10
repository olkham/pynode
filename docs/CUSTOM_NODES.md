# Creating Custom Nodes

This guide will walk you through creating custom nodes for PyNode. Nodes are self-contained Python classes that define their own behavior, appearance, and configuration options.

## Table of Contents

- [Basic Node Structure](#basic-node-structure)
- [Node Properties](#node-properties)
- [Configuration](#configuration)
- [Message Processing](#message-processing)
- [Node Lifecycle](#node-lifecycle)
- [Examples](#examples)

## Basic Node Structure

Every node inherits from `BaseNode` and follows this basic structure:

```python
from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from typing import Any, Dict

class MyNode(BaseNode):
    """
    My custom node description.
    """
    
    # Visual properties
    display_name = 'My Node'
    icon = '🔧'
    category = 'custom'
    color = '#FFA07A'
    border_color = '#FF7F50'
    text_color = '#000000'
    
    # I/O configuration
    input_count = 1
    output_count = 1
    
    # Default configuration
    DEFAULT_CONFIG = {
        'my_setting': 'default_value',
        MessageKeys.DROP_MESSAGES: 'false'
    }
    
    # Property schema for UI
    properties = [
        {
            'name': 'my_setting',
            'label': 'My Setting',
            'type': 'text',
            'default': 'default_value',
            'help': 'Description of this setting'
        }
    ]
    
    def __init__(self, node_id=None, name="my node"):
        super().__init__(node_id, name)
        # Initialize any instance variables here
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Process incoming messages.
        
        Args:
            msg: The message dictionary
            input_index: Which input received the message (for multi-input nodes)
        """
        # Get configuration values
        my_setting = self.config.get('my_setting', 'default_value')
        
        # Process the message
        payload = msg.get(MessageKeys.PAYLOAD)
        
        # Modify and send
        msg[MessageKeys.PAYLOAD] = self.process(payload, my_setting)
        self.send(msg)
    
    def process(self, payload, setting):
        """Your custom processing logic."""
        return payload
```

## Node Properties

### Visual Properties

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `display_name` | str | Name shown in the UI | `'My Node'` |
| `icon` | str | Emoji or icon | `'🔧'` |
| `category` | str | Palette category | `'custom'`, `'analysis'`, `'vision'` |
| `color` | str | Background color (hex) | `'#FFA07A'` |
| `border_color` | str | Border color (hex) | `'#FF7F50'` |
| `text_color` | str | Text color (hex) | `'#000000'` |

### I/O Configuration

| Property | Type | Description | Example |
|----------|------|-------------|---------|
| `input_count` | int | Number of inputs | `1` |
| `output_count` | int | Number of outputs | `2` |

### Info Documentation

Use the `Info` class to create rich documentation that appears in the UI:

```python
from pynode.nodes.base_node import Info, MessageKeys

_info = Info()
_info.add_text("This node processes messages in a special way.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Primary data stream"),
    ("Input 1:", "Control messages")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Processed data"),
    ("Output 1:", "Error messages")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Threshold:", "Minimum value to process (default: 0.5)"),
    ("Mode:", "Processing mode: 'fast' or 'accurate'")
)
_info.add_header("Example Usage")
_info.add_code('msg.payload = {"value": 42, "name": "test"}')

class MyNode(BaseNode):
    info = str(_info)
    # ... rest of the class
```

## Configuration

### Property Types

PyNode supports several property types in the UI:

#### Text Input
```python
{
    'name': 'text_field',
    'label': 'Text Field',
    'type': 'text',
    'default': 'default value',
    'help': 'Enter text here'
}
```

#### Number Input
```python
{
    'name': 'number_field',
    'label': 'Number',
    'type': 'number',
    'default': 42,
    'help': 'Enter a number'
}
```

#### Textarea
```python
{
    'name': 'code_field',
    'label': 'Code',
    'type': 'textarea',
    'default': 'print("hello")',
    'help': 'Enter Python code'
}
```

#### Select Dropdown
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
    'help': 'Choose processing mode'
}
```

#### Checkbox
```python
{
    'name': 'enabled',
    'label': 'Enable Feature',
    'type': 'checkbox',
    'default': True,
    'help': 'Enable or disable this feature'
}
```

#### Button (triggers action)
```python
{
    'name': 'reset_button',
    'label': 'Reset',
    'type': 'button',
    'action': 'reset_counter',
    'help': 'Reset the counter to zero'
}
```

### Accessing Configuration

Use helper methods to safely access configuration values:

```python
def on_input(self, msg, input_index=0):
    # String values
    text = self.config.get('text_field', 'default')
    
    # Boolean values (handles string 'true'/'false')
    enabled = self.get_config_bool('enabled', False)
    
    # Integer values
    count = self.get_config_int('count', 0)
    
    # Float values
    threshold = self.get_config_float('threshold', 0.5)
```

## Message Processing

### Message Structure

Messages follow the Node-RED format:

```python
{
    'payload': Any,              # Main data
    'topic': str,                # Optional topic
    '_msgid': str,               # Unique message ID
    '_queue_length': int,        # Queue depth (added by engine)
    # ... any additional fields
}
```

### Creating Messages

```python
# Create a new message
msg = self.create_message(
    payload={'result': 42},
    topic='my/topic'
)

# Preserve existing message properties
msg[MessageKeys.PAYLOAD] = new_payload
msg[MessageKeys.TOPIC] = 'updated/topic'
```

### Sending Messages

```python
# Send to default output (0)
self.send(msg)

# Send to specific output
self.send(msg, output_index=1)

# Send multiple messages
for item in items:
    new_msg = self.create_message(payload=item)
    self.send(new_msg)

# Send to multiple outputs
self.send(msg, output_index=0)  # Primary output
error_msg = self.create_message(payload='error')
self.send(error_msg, output_index=1)  # Error output
```

### Filtering Messages

```python
def on_input(self, msg, input_index=0):
    payload = msg.get(MessageKeys.PAYLOAD)
    
    # Only send if condition is met
    if payload > threshold:
        self.send(msg)
    # Otherwise, message is dropped (not sent)
```

## Node Lifecycle

### Initialization

```python
def __init__(self, node_id=None, name="my node"):
    super().__init__(node_id, name)
    # Initialize instance variables
    self._counter = 0
    self._buffer = []
```

### Starting

Override `on_start()` to initialize resources when workflow starts:

```python
def on_start(self):
    """Called when workflow starts."""
    super().on_start()  # Always call parent
    self._counter = 0
    self._buffer.clear()
    print(f"{self.name} started")
```

### Stopping

Override `on_stop()` to clean up resources:

```python
def on_stop(self):
    """Called when workflow stops."""
    self._buffer.clear()
    print(f"{self.name} stopped")
    super().on_stop()  # Always call parent
```

### Configuration Updates

Override `configure()` to react to configuration changes:

```python
def configure(self, config: Dict[str, Any]):
    """Called when node configuration changes."""
    super().configure(config)  # Always call parent
    
    # React to config changes
    if self.get_config_bool('reset_on_config', False):
        self._counter = 0
```

## Examples

### Example 1: Simple Transformer

Transform message payloads:

```python
from pynode.nodes.base_node import BaseNode, MessageKeys

class MultiplyNode(BaseNode):
    display_name = 'Multiply'
    icon = '✖️'
    category = 'math'
    color = '#90EE90'
    border_color = '#32CD32'
    
    DEFAULT_CONFIG = {
        'multiplier': '2',
        MessageKeys.DROP_MESSAGES: 'false'
    }
    
    properties = [
        {
            'name': 'multiplier',
            'label': 'Multiplier',
            'type': 'number',
            'default': 2,
            'help': 'Multiply payload by this value'
        },
        {
            'name': MessageKeys.DROP_MESSAGES,
            'label': 'Drop Messages When Busy',
            'type': 'checkbox',
            'default': False
        }
    ]
    
    def on_input(self, msg, input_index=0):
        multiplier = self.get_config_float('multiplier', 2.0)
        payload = msg.get(MessageKeys.PAYLOAD, 0)
        
        try:
            result = float(payload) * multiplier
            msg[MessageKeys.PAYLOAD] = result
            self.send(msg)
        except (ValueError, TypeError):
            self.report_error(f"Cannot multiply non-numeric payload: {payload}")
```

### Example 2: Filter Node

Filter messages based on criteria:

```python
class ThresholdFilterNode(BaseNode):
    display_name = 'Threshold Filter'
    icon = '🔍'
    category = 'filter'
    color = '#FFB347'
    border_color = '#FF8C00'
    output_count = 2  # Pass and fail outputs
    
    DEFAULT_CONFIG = {
        'threshold': '50',
        'comparison': 'greater',
        MessageKeys.DROP_MESSAGES: 'false'
    }
    
    properties = [
        {
            'name': 'threshold',
            'label': 'Threshold',
            'type': 'number',
            'default': 50
        },
        {
            'name': 'comparison',
            'label': 'Comparison',
            'type': 'select',
            'options': [
                {'value': 'greater', 'label': 'Greater Than'},
                {'value': 'less', 'label': 'Less Than'},
                {'value': 'equal', 'label': 'Equal To'}
            ],
            'default': 'greater'
        },
        {
            'name': MessageKeys.DROP_MESSAGES,
            'label': 'Drop Messages When Busy',
            'type': 'checkbox',
            'default': False
        }
    ]
    
    def on_input(self, msg, input_index=0):
        threshold = self.get_config_float('threshold', 50.0)
        comparison = self.config.get('comparison', 'greater')
        payload = msg.get(MessageKeys.PAYLOAD, 0)
        
        try:
            value = float(payload)
            passes = False
            
            if comparison == 'greater' and value > threshold:
                passes = True
            elif comparison == 'less' and value < threshold:
                passes = True
            elif comparison == 'equal' and value == threshold:
                passes = True
            
            # Send to output 0 if passes, output 1 if fails
            self.send(msg, output_index=0 if passes else 1)
        except (ValueError, TypeError):
            # Send to fail output
            self.send(msg, output_index=1)
```

### Example 3: Stateful Node

Maintain state across messages:

```python
class BufferNode(BaseNode):
    display_name = 'Buffer'
    icon = '📦'
    category = 'utility'
    color = '#87CEEB'
    border_color = '#4682B4'
    
    DEFAULT_CONFIG = {
        'buffer_size': '10',
        MessageKeys.DROP_MESSAGES: 'false'
    }
    
    properties = [
        {
            'name': 'buffer_size',
            'label': 'Buffer Size',
            'type': 'number',
            'default': 10,
            'help': 'Number of messages to buffer'
        },
        {
            'name': MessageKeys.DROP_MESSAGES,
            'label': 'Drop Messages When Busy',
            'type': 'checkbox',
            'default': False
        }
    ]
    
    def __init__(self, node_id=None, name="buffer"):
        super().__init__(node_id, name)
        self._buffer = []
    
    def on_input(self, msg, input_index=0):
        buffer_size = self.get_config_int('buffer_size', 10)
        
        # Add to buffer
        self._buffer.append(msg.get(MessageKeys.PAYLOAD))
        
        # Keep buffer at size limit
        if len(self._buffer) > buffer_size:
            self._buffer.pop(0)
        
        # Send buffer contents
        output_msg = self.create_message(
            payload=self._buffer.copy(),
            topic='buffer'
        )
        self.send(output_msg)
    
    def on_stop(self):
        self._buffer.clear()
        super().on_stop()
```

### Example 4: Action Handler

Handle button clicks from UI:

```python
class ResettableCounterNode(BaseNode):
    display_name = 'Counter'
    icon = '🔢'
    category = 'analysis'
    color = '#E2D96E'
    border_color = '#B8AF4A'
    ui_component = 'counter-display'
    
    DEFAULT_CONFIG = {
        'initial_value': '0',
        MessageKeys.DROP_MESSAGES: 'false'
    }
    
    properties = [
        {
            'name': 'initial_value',
            'label': 'Initial Value',
            'type': 'number',
            'default': 0
        },
        {
            'name': MessageKeys.DROP_MESSAGES,
            'label': 'Drop Messages When Busy',
            'type': 'checkbox',
            'default': False
        }
    ]
    
    def __init__(self, node_id=None, name="counter"):
        super().__init__(node_id, name)
        self.count = 0
    
    def on_input(self, msg, input_index=0):
        self.count += 1
        msg[MessageKeys.PAYLOAD] = {'count': self.count}
        self.send(msg)
    
    def reset_counter(self):
        """Called when reset button is clicked in UI."""
        self.count = self.get_config_int('initial_value', 0)
        print(f"Counter {self.name} reset to {self.count}")
```

## Node Organization

Create a folder for your node in `pynode/nodes/`:

```
pynode/nodes/
└── MyCustomNode/
    ├── __init__.py           # Import your node class
    ├── my_custom_node.py     # Node implementation
    ├── requirements.txt      # Node-specific dependencies (optional)
    └── README.md             # Documentation (optional)
```

**`__init__.py`:**
```python
from .my_custom_node import MyCustomNode

__all__ = ['MyCustomNode']
```

The workflow engine will automatically discover and register your node when it starts.

## Best Practices

1. **Always call parent methods**: When overriding `__init__`, `on_start()`, `on_stop()`, or `configure()`, always call the parent method.

2. **Use MessageKeys constants**: Import and use `MessageKeys.PAYLOAD`, `MessageKeys.TOPIC`, etc. instead of hardcoded strings.

3. **Handle errors gracefully**: Use try-except blocks and call `self.report_error()` to send errors to ErrorNodes.

4. **Document your nodes**: Use the `Info` class to create comprehensive documentation.

5. **Include drop_messages property**: Always include the `drop_messages` property in your `properties` array with `default: False` for analysis/monitoring nodes.

6. **Deep copy when needed**: If you need to send different messages to multiple outputs, create new message objects instead of modifying the same one.

7. **Clean up resources**: Override `on_stop()` to close files, connections, or free resources.

8. **Test with different payload types**: Ensure your node handles various payload types (numbers, strings, dicts, arrays, None).

## Next Steps

- See [UI_COMPONENTS.md](UI_COMPONENTS.md) for adding interactive UI components to your nodes
- See [EXTENSIBILITY.md](EXTENSIBILITY.md) for architecture details
- Check the `pynode/nodes/` directory for more examples
