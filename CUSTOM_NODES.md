# Creating Custom Nodes

This guide explains how to create your own custom nodes for PyNode.

## Overview

PyNode is designed to be fully extensible. All node information (visual properties, property schemas, behavior) is contained within the node class itself. The main application has no hardcoded knowledge of specific node types.

## Node Structure

Every node inherits from `BaseNode` and can define:

1. **Visual Properties** - How the node appears in the palette and canvas
2. **Property Schema** - What fields appear in the properties panel
3. **Behavior** - What the node does when it receives messages

## Creating a New Node

### 1. Create a new Python file in the `nodes/` directory

Example: `nodes/my_custom_node.py`

```python
from typing import Any, Dict
from base_node import BaseNode

class MyCustomNode(BaseNode):
    """
    Description of what your node does.
    """
    # Visual properties
    category = 'custom'  # Categories: input, output, function, logic, custom
    color = '#FFA07A'
    border_color = '#FF7F50'
    text_color = '#000000'
    
    # Property schema
    properties = [
        {
            'name': 'myProperty',
            'label': 'My Property',
            'type': 'text'
        }
    ]
    
    def __init__(self, node_id=None, name="my_custom"):
        super().__init__(node_id, name)
        self.configure({
            'myProperty': 'default value'
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Called when a message arrives."""
        # Your processing logic here
        payload = msg.get('payload')
        
        # Do something with the payload
        result = self.process(payload)
        
        # Send output
        new_msg = self.create_message(
            payload=result,
            topic=msg.get('topic', '')
        )
        self.send(new_msg)
    
    def process(self, payload):
        """Your custom processing logic."""
        return payload
```

### 2. Visual Properties

Define how your node appears:

```python
category = 'custom'      # Where it appears in the palette
color = '#FFA07A'        # Background color
border_color = '#FF7F50' # Border color
text_color = '#000000'   # Text color
```

**Available Categories:**
- `input` - Nodes that generate or receive messages
- `output` - Nodes that output or store messages
- `function` - Nodes that transform messages
- `logic` - Nodes that route messages
- `custom` - Your custom nodes

**Color Guidelines:**
- Input nodes: Light blue (`#C0DEED`)
- Output nodes: Light green (`#87A980`)
- Function nodes: Light purple (`#E6E0F8`)
- Logic nodes: Salmon (`#E9967A`)
- Custom: Your choice!

### 3. Property Schema

Define what fields appear in the properties panel:

```python
properties = [
    {
        'name': 'fieldName',      # Config key
        'label': 'Display Label',  # What users see
        'type': 'text',            # Field type
        'help': 'Optional help'    # Optional help text
    }
]
```

**Available Field Types:**

#### Text Input
```python
{
    'name': 'username',
    'label': 'Username',
    'type': 'text'
}
```

#### Textarea
```python
{
    'name': 'code',
    'label': 'Code',
    'type': 'textarea'
}
```

#### Select Dropdown
```python
{
    'name': 'format',
    'label': 'Format',
    'type': 'select',
    'options': [
        {'value': 'json', 'label': 'JSON'},
        {'value': 'xml', 'label': 'XML'}
    ]
}
```

#### Button (triggers node method)
```python
{
    'name': 'trigger',
    'label': 'Trigger Now',
    'type': 'button',
    'action': 'trigger'  # Calls POST /api/nodes/{id}/trigger
}
```

For buttons, implement a corresponding method:
```python
def trigger(self):
    """Called when button is clicked."""
    msg = self.create_message(payload='triggered!')
    self.send(msg)
```

### 4. Node Behavior

Implement the `on_input` method to process messages:

```python
def on_input(self, msg: Dict[str, Any], input_index: int = 0):
    """
    Called when a message arrives.
    
    Args:
        msg: Dictionary with 'payload', 'topic', '_msgid'
        input_index: Which input port (default 0)
    """
    # Access config values
    my_setting = self.config.get('myProperty', 'default')
    
    # Process the message
    payload = msg.get('payload')
    result = self.do_something(payload)
    
    # Send output
    new_msg = self.create_message(
        payload=result,
        topic=msg.get('topic', '')
    )
    self.send(new_msg)
```

### 5. Register Your Node

In `app.py`, import and register your node:

```python
from nodes import MyCustomNode

# Register the node type
engine.register_node_type(MyCustomNode)
```

Or better yet, add it to `nodes/__init__.py`:

```python
from .my_custom_node import MyCustomNode

__all__ = [
    'InjectNode',
    'FunctionNode',
    'DebugNode',
    'ChangeNode',
    'SwitchNode',
    'DelayNode',
    'MyCustomNode'  # Add your node here
]
```

Then import in `app.py`:
```python
from nodes import MyCustomNode
engine.register_node_type(MyCustomNode)
```

## Example: Timer Node

Here's a complete example of a timer node:

```python
import time
from typing import Any, Dict
from base_node import BaseNode

class TimerNode(BaseNode):
    """Triggers messages at regular intervals."""
    
    category = 'input'
    color = '#C0DEED'
    border_color = '#87A9C1'
    text_color = '#000000'
    
    properties = [
        {
            'name': 'interval',
            'label': 'Interval (seconds)',
            'type': 'text'
        },
        {
            'name': 'start',
            'label': 'Start Timer',
            'type': 'button',
            'action': 'start'
        }
    ]
    
    def __init__(self, node_id=None, name="timer"):
        super().__init__(node_id, name)
        self.configure({
            'interval': 5
        })
        self.running = False
    
    def start(self):
        """Start the timer."""
        if not self.running:
            self.running = True
            import threading
            threading.Thread(target=self._run_timer, daemon=True).start()
    
    def _run_timer(self):
        """Timer loop."""
        while self.running:
            msg = self.create_message(
                payload=time.time(),
                topic='timer'
            )
            self.send(msg)
            time.sleep(float(self.config.get('interval', 5)))
    
    def on_close(self):
        """Called when node is deleted."""
        self.running = False
```

## Best Practices

1. **Use descriptive names** - Make your node type clear
2. **Provide default config** - Set sensible defaults in `__init__`
3. **Handle errors gracefully** - Use try/except in `on_input`
4. **Document your node** - Add docstrings explaining what it does
5. **Clean up resources** - Implement `on_close()` if needed
6. **Test thoroughly** - Create test workflows before sharing

## Message Structure

All messages follow Node-RED format:

```python
{
    'payload': <any>,          # The message data
    'topic': <string>,         # Optional message topic
    '_msgid': <string>         # Unique message ID
}
```

Create messages using:
```python
msg = self.create_message(payload=data, topic='my-topic')
```

Send messages using:
```python
self.send(msg)  # Send to all connected nodes
self.send(msg, output_index=0)  # Send to specific output
```

## Distributing Your Node

To share your node:

1. Create a single Python file with your node class
2. Document the node's purpose and configuration
3. Share the file - users can drop it in their `nodes/` directory
4. Update their `nodes/__init__.py` to include it
5. Register it in `app.py`

That's it! The node will automatically appear in the palette with the correct colors, properties, and behavior.
