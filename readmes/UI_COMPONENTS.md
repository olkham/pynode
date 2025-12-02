# Node UI Components Guide

This guide explains how to add custom UI controls to your nodes that appear directly in the node card on the canvas.

## Overview

Nodes can define custom UI components that are rendered in the node's visual representation. This allows for interactive controls without opening the properties panel.

## Available UI Components

### 1. Button Component

A clickable button that triggers an action on the node.

**Use case:** Manually trigger node actions (e.g., InjectNode)

**Configuration:**
```python
class MyNode(BaseNode):
    display_name = 'My Node'
    icon = '▶'
    category = 'custom'
    input_count = 0
    output_count = 1
    
    ui_component = 'button'
    ui_component_config = {
        'icon': '▶',           # Icon/text shown in button
        'action': 'trigger',   # Action name (maps to method or endpoint)
        'tooltip': 'Run Now'   # Hover tooltip text
    }
    
    def trigger(self):
        """Called when button is clicked"""
        msg = self.create_message(payload="triggered")
        self.send(msg)
```

### 2. Toggle Component

An on/off switch for real-time node control.

**Use case:** Enable/disable node behavior without redeployment (e.g., GateNode, DebugNode)

**Configuration:**
```python
class MyGateNode(BaseNode):
    display_name = 'My Gate'
    icon = '🚪'
    category = 'logic'
    input_count = 1
    output_count = 1
    
    ui_component = 'toggle'
    ui_component_config = {
        'action': 'toggle_state',  # Action name
        'label': 'Open'            # Label for toggle (optional)
    }
    
    def __init__(self, node_id=None, name="my gate"):
        super().__init__(node_id, name)
        self.enabled = True
    
    def on_input(self, msg, input_index=0):
        """Only pass messages when enabled"""
        if self.enabled:
            self.send(msg)
```

**Backend handler:**
The toggle state is automatically managed via the `/api/nodes/<id>/enabled` endpoint. The `enabled` property on your node instance will be updated.

### 3. Rate Display Component

A read-only display showing numeric values (e.g., rate, count, temperature).

**Use case:** Display real-time metrics or status (e.g., RateProbeNode showing messages/second)

**Configuration:**
```python
class MyProbeNode(BaseNode):
    display_name = 'My Probe'
    icon = '📊'
    category = 'function'
    input_count = 1
    output_count = 1
    
    ui_component = 'rate-display'
    ui_component_config = {
        'format': '{value}/s',  # Display format
        'precision': 1          # Decimal places
    }
    
    def on_input(self, msg, input_index=0):
        """Update the display via message payload"""
        # Send rate info to update the UI display
        rate_msg = self.create_message(
            payload={
                'rate': 42.5,  # The value to display
                'display': self.get_rate_display()
            }
        )
        self.send(rate_msg)
```

**Note:** The display is updated via SSE (Server-Sent Events) when the node outputs messages containing rate information.

## Component Placement

Components are automatically positioned based on node type:

- **Input nodes** (no inputs, has outputs): Button/icon on left, controls on right
- **Output nodes** (has inputs, no outputs): Title first, then icon, then controls on right  
- **Processing nodes** (has both): Icon and title center, controls on right

## Action Handlers

### Frontend Actions

When a UI component triggers an action, it calls:
```javascript
window.nodeAction(nodeId, action, value)
```

This automatically routes to the appropriate handler:
- `inject` → `/api/nodes/<id>/inject`
- `toggle_gate` → Updates `enabled` property
- `toggle_debug` → Updates `enabled` property
- `toggle_drawing` → `/api/nodes/<id>/toggle_drawing`
- Custom actions → `/api/nodes/<id>/<action>`

### Backend Action Endpoints

For custom button actions, implement a Flask route in `app.py`:

```python
@app.route('/api/nodes/<node_id>/my_action', methods=['POST'])
def my_action(node_id):
    node = deployed_engine.get_node(node_id)
    if node:
        # Call node method
        node.my_action()
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Node not found'}), 404
```

Or implement the action method directly in your node class:
```python
def my_action(self):
    """Custom action triggered by button"""
    self.report_error("Action triggered!")
    # ... do something
```

## Complete Example: Custom Timer Node

Here's a complete example of a node with a button UI component:

**nodes/TimerNode/timer_node.py:**
```python
"""
Timer node - manually triggered timer
"""
import time
from nodes.base_node import BaseNode


class TimerNode(BaseNode):
    display_name = 'Timer'
    icon = '⏱️'
    category = 'function'
    color = '#FFE5B4'
    border_color = '#FFD700'
    text_color = '#000000'
    input_count = 0
    output_count = 1
    
    # Button UI component
    ui_component = 'button'
    ui_component_config = {
        'icon': '▶',
        'action': 'start_timer',
        'tooltip': 'Start Timer'
    }
    
    properties = [
        {
            'name': 'duration',
            'label': 'Duration (seconds)',
            'type': 'text',
            'default': '5'
        }
    ]
    
    def __init__(self, node_id=None, name="timer"):
        super().__init__(node_id, name)
        self.configure({'duration': '5'})
    
    def start_timer(self):
        """Action triggered by button click"""
        duration = float(self.config.get('duration', 5))
        start_time = time.time()
        
        msg = self.create_message(
            payload={
                'action': 'started',
                'duration': duration,
                'start_time': start_time
            }
        )
        self.send(msg)
```

**nodes/TimerNode/__init__.py:**
```python
from .timer_node import TimerNode
```

**Register in nodes/__init__.py:**
```python
from .TimerNode import TimerNode

def get_all_node_types():
    return [
        # ... existing nodes ...
        TimerNode,
    ]
```

## Best Practices

1. **Keep it simple**: UI components should provide quick access to common actions. Complex configuration still belongs in the properties panel.

2. **Use appropriate components**: 
   - Button for one-time actions
   - Toggle for on/off states that persist
   - Rate display for real-time metrics

3. **Provide tooltips**: Always set meaningful tooltips for buttons to guide users.

4. **Handle state properly**: Toggle components automatically sync with the `enabled` property. For custom state, implement your own property.

5. **Action naming**: Use descriptive action names that indicate what the action does (e.g., `start_recording`, `reset_counter`).

6. **Visual feedback**: When your action completes, consider sending a message to a DebugNode to confirm success.

## Styling

UI components use the existing CSS classes from `style.css`:
- `.inject-btn` - Button component
- `.gate-switch` - Toggle switch component
- `.rate-display` - Rate display component

You can customize colors via the node's color properties:
```python
color = '#FFE5B4'          # Background color
border_color = '#FFD700'   # Border color
text_color = '#000000'     # Text color (also affects UI components)
```

## Future Extensions

Additional UI component types planned:
- `dropdown` - Select from options
- `slider` - Numeric range control
- `badge` - Status indicator (color + text)
- `sparkline` - Mini time-series chart

To request a new component type, open an issue on GitHub.
