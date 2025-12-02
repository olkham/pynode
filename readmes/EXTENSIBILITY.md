# Extensibility Refactoring Summary

## Changes Made

The PyNode system has been refactored to be fully extensible. All node-specific information is now contained within the node classes themselves, with no hardcoded knowledge in the main application.

## What Changed

### 1. BaseNode Class (base_node.py)
- Added class-level properties for visual styling:
  - `category`: Node category (input/output/function/logic/custom)
  - `color`: Background color
  - `border_color`: Border color
  - `text_color`: Text color
- Added `properties` schema list to define UI fields

### 2. All Node Classes
Each node now defines its complete schema:

#### InjectNode
- Payload type selector (timestamp, string, number, boolean, JSON)
- Payload input field
- Inject button

#### FunctionNode
- Function code textarea

#### DebugNode
- Output selector (payload or complete message)

#### ChangeNode, SwitchNode, DelayNode
- Basic text inputs for configuration

### 3. API Updates (app.py)
- `/api/node-types` endpoint now includes:
  - Visual properties (category, colors)
  - Property schemas for each node type
- No hardcoded node-specific logic in API

### 4. Frontend Updates (app.js)
- `renderProperties()` function now dynamically renders UI based on node schema
- Supports field types:
  - `text`: Single-line text input
  - `textarea`: Multi-line text area
  - `select`: Dropdown with options
  - `button`: Action button (triggers POST to node action endpoint)
- Added `triggerNodeAction()` for generic button actions
- Removed all hardcoded node type checks (InjectNode, FunctionNode, etc.)

### 5. Styling (style.css)
- Added `.property-help` style for optional help text

### 6. New Files

#### nodes/template_node.py
- Example custom node showing extensibility
- Template replacement functionality
- Demonstrates all property types

#### CUSTOM_NODES.md
- Complete guide for creating custom nodes
- Documents property schema format
- Shows examples and best practices
- Explains node lifecycle and message structure

## Benefits

1. **Zero Core Modification**: Add new nodes without touching app.py or app.js
2. **Self-Describing**: Each node carries its own metadata
3. **Automatic UI**: Properties panel automatically generated from schema
4. **Third-Party Ready**: External developers can create nodes easily
5. **Type Safe**: Property schema ensures consistent UI rendering

## How to Add a New Node

1. Create a Python file in `nodes/` directory
2. Define class with:
   - Visual properties (category, colors)
   - Property schema
   - Behavior (on_input method)
3. Import in `nodes/__init__.py`
4. Register in `app.py`: `engine.register_node_type(YourNode)`
5. Restart server - node appears in palette automatically

That's it! No frontend changes needed, no API updates required.

## Property Schema Format

```python
properties = [
    {
        'name': 'configKey',        # Key in node.config
        'label': 'Display Label',   # Shown in UI
        'type': 'text',             # Field type
        'options': [...],           # For 'select' type
        'action': 'methodName',     # For 'button' type
        'help': 'Help text'         # Optional help
    }
]
```

## Supported Field Types

- **text**: `<input type="text">`
- **textarea**: `<textarea>` for multi-line
- **select**: `<select>` dropdown with options
- **button**: `<button>` that triggers node method via API

## Example Third-Party Node

```python
from base_node import BaseNode

class TemperatureConverter(BaseNode):
    category = 'function'
    color = '#FFB6C1'
    border_color = '#FF69B4'
    text_color = '#000000'
    
    properties = [
        {
            'name': 'unit',
            'label': 'Convert To',
            'type': 'select',
            'options': [
                {'value': 'celsius', 'label': 'Celsius'},
                {'value': 'fahrenheit', 'label': 'Fahrenheit'}
            ]
        }
    ]
    
    def __init__(self, node_id=None, name="temp_converter"):
        super().__init__(node_id, name)
        self.configure({'unit': 'celsius'})
    
    def on_input(self, msg, input_index=0):
        temp = float(msg['payload'])
        unit = self.config['unit']
        
        if unit == 'celsius':
            result = (temp - 32) * 5/9
        else:
            result = temp * 9/5 + 32
        
        self.send(self.create_message(result, msg.get('topic', '')))
```

Drop this in `nodes/temperature_converter.py`, register it in `app.py`, and it's ready to use!
