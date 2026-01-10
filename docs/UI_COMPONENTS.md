# UI Components Guide

PyNode allows nodes to display interactive UI components directly on the node card. This guide covers how to add buttons, toggles, displays, and custom controls to your nodes.

## Table of Contents

- [Overview](#overview)
- [Built-in Components](#built-in-components)
- [Creating Custom Components](#creating-custom-components)
- [Server-Side Event (SSE) Updates](#server-side-event-sse-updates)
- [Examples](#examples)

## Overview

UI components are defined in the node class and automatically rendered in the web interface. Components can:

- Display dynamic data (counters, rates, values)
- Trigger node actions (buttons, toggles)
- Update in real-time via Server-Sent Events (SSE)
- Be styled consistently with the node's color scheme

## Built-in Components

### Inject Button

Allows manual triggering of nodes (typically InjectNode).

**Node Configuration:**
```python
class InjectNode(BaseNode):
    ui_component = 'inject-btn'
    ui_component_config = {
        'action': 'inject',
        'tooltip': 'Inject Message'
    }
```

**Action Handler:**
```python
def inject(self):
    """Called when button is clicked."""
    msg = self.create_message(
        payload=self.config.get('payload', ''),
        topic=self.config.get('topic', '')
    )
    self.send(msg)
```

### Gate Toggle

Toggle switch for controlling message flow.

**Node Configuration:**
```python
class GateNode(BaseNode):
    ui_component = 'gate-switch'
    ui_component_config = {
        'action': 'toggle_gate',
        'tooltip': 'Toggle Gate'
    }
```

**Action Handler:**
```python
def __init__(self, node_id=None, name="gate"):
    super().__init__(node_id, name)
    self.gate_open = True

def toggle_gate(self):
    """Called when toggle is clicked."""
    self.gate_open = not self.gate_open
    return {'open': self.gate_open}
```

### Rate Display

Displays real-time message throughput rate with SSE updates.

**Node Configuration:**
```python
class RateProbeNode(BaseNode):
    ui_component = 'rate-display'
    ui_component_config = {
        'format': '{value}/s',
        'precision': 1
    }
```

**Display Methods:**
```python
def get_rate(self) -> float:
    """Return the current rate value."""
    return self._current_rate

def get_rate_display(self) -> str:
    """Return formatted string for display."""
    rate = self.get_rate()
    if rate >= 1000:
        return f"{rate/1000:.1f}k/s"
    elif rate >= 1:
        return f"{rate:.1f}/s"
    else:
        return "0/s"
```

### Queue Length Display

Displays message queue depth with SSE updates.

**Node Configuration:**
```python
class QueueLengthProbeNode(BaseNode):
    ui_component = 'queue-length-display'
    ui_component_config = {
        'format': '{value} queued',
        'precision': 0
    }
```

**Display Methods:**
```python
def get_queue_length(self) -> int:
    """Return current queue length."""
    return self._current_queue_length

def get_queue_length_display(self) -> str:
    """Return formatted string for display."""
    return f"{self._current_queue_length} queued"
```

### Counter Display

Displays a count with reset button and SSE updates.

**Node Configuration:**
```python
class CounterNode(BaseNode):
    ui_component = 'counter-display'
    ui_component_config = {
        'format': '{value}',
        'action': 'reset_counter',
        'tooltip': 'Reset Count'
    }
```

**Display and Action Methods:**
```python
def get_count(self) -> int:
    """Return current count."""
    return self.count

def get_count_display(self) -> str:
    """Return formatted string for display."""
    return str(self.count)

def reset_counter(self):
    """Called when reset button is clicked."""
    self.count = self.get_config_int('initial_value', 0)
```

## Creating Custom Components

### Step 1: Define in Node Class

```python
class MyCustomNode(BaseNode):
    display_name = 'Custom Node'
    ui_component = 'custom-display'  # Component name
    ui_component_config = {
        'format': '{value}',
        'action': 'custom_action',  # Optional button action
        'tooltip': 'Click to do something'
    }
    
    def get_custom_value(self):
        """Return the value to display."""
        return self._custom_value
    
    def get_custom_display(self) -> str:
        """Return formatted display string."""
        return f"Value: {self._custom_value}"
    
    def custom_action(self):
        """Handle button click."""
        self._custom_value = 0
        return {'value': self._custom_value}
```

### Step 2: Add Frontend Rendering (nodes.js)

Add to the `renderNode()` function in `pynode/static/js/nodes.js`:

```javascript
// In the UI component rendering section
if (uiComponent === 'custom-display') {
    const button = document.createElement('button');
    button.className = 'custom-action-btn';
    button.textContent = '◀';
    button.title = nodeType.ui_component_config?.tooltip || 'Action';
    button.addEventListener('click', async (e) => {
        e.stopPropagation();
        try {
            const response = await fetch(`/api/nodes/${nodeData.id}/custom_action`, {
                method: 'POST'
            });
            if (response.ok) {
                console.log('Action triggered');
            }
        } catch (error) {
            console.error('Action failed:', error);
        }
    });
    nodeContent.appendChild(button);

    const display = document.createElement('div');
    display.className = 'custom-display';
    display.id = `custom-${nodeData.id}`;
    display.textContent = '0';
    nodeContent.appendChild(display);
}
```

### Step 3: Add CSS Styling (style.css)

Add to `pynode/static/style.css`:

```css
/* Custom display styling */
.custom-display {
    font-size: 11px;
    font-weight: 600;
    color: #000;
    background: rgba(255, 255, 255, 0.3);
    padding: 2px 6px;
    border-radius: 3px;
    margin-left: 8px;
    margin-right: 8px;
    min-width: 40px;
    text-align: center;
}

/* Action button */
.custom-action-btn {
    width: 22px;
    height: 22px;
    border: 1px solid rgba(0, 0, 0, 0.3);
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.25);
    cursor: pointer;
    font-size: 12px;
    margin-left: 4px;
    margin-right: 4px;
}

.custom-action-btn:hover {
    background: rgba(255, 255, 255, 0.5);
}

/* Alignment for the component */
.node-content .custom-display {
    align-self: center;
}
```

### Step 4: Add Real-time Updates (Optional)

If you want real-time updates via SSE:

**In debug.js:**
```javascript
// Add SSE event handler
eventSource.addEventListener('custom', function(e) {
    const data = JSON.parse(e.data);
    updateCustomDisplay(data);
});

function updateCustomDisplay(data) {
    const displayElement = document.getElementById(`custom-${data.node_id}`);
    if (displayElement) {
        displayElement.textContent = data.display;
    }
}
```

**In server.py:**
```python
# In the SSE broadcast function
elif node.type == 'MyCustomNode':
    updates.append({
        'type': 'custom',
        'node_id': node.id,
        'value': node.get_custom_value(),
        'display': node.get_custom_display()
    })
```

## Server-Side Event (SSE) Updates

SSE allows nodes to push updates to the UI in real-time without polling.

### Backend Setup

In `server.py`, the SSE endpoint broadcasts updates:

```python
@app.route('/api/events')
def events():
    def generate():
        last_broadcast = 0
        broadcast_interval = 0.1  # Throttle to 100ms
        
        while True:
            current_time = time.time()
            if current_time - last_broadcast >= broadcast_interval:
                updates = []
                
                for node in engine.nodes.values():
                    if node.type == 'RateProbeNode':
                        updates.append({
                            'type': 'rate',
                            'node_id': node.id,
                            'rate': node.get_rate(),
                            'display': node.get_rate_display()
                        })
                
                if updates:
                    yield f"data: {json.dumps(updates)}\n\n"
                
                last_broadcast = current_time
            
            time.sleep(0.05)
    
    return Response(generate(), mimetype='text/event-stream')
```

### Frontend Setup

In `debug.js`, create EventSource connection:

```javascript
const eventSource = new EventSource('/api/events');

eventSource.addEventListener('rate', function(e) {
    const data = JSON.parse(e.data);
    updateRateDisplay(data);
});

function updateRateDisplay(data) {
    const displayElement = document.getElementById(`rate-${data.node_id}`);
    if (displayElement) {
        displayElement.textContent = data.display;
    }
}
```

## Examples

### Example 1: Status Indicator

Display node status with color-coded indicator:

**Node Class:**
```python
class MonitorNode(BaseNode):
    display_name = 'Monitor'
    ui_component = 'status-indicator'
    
    def __init__(self, node_id=None, name="monitor"):
        super().__init__(node_id, name)
        self.status = 'idle'  # idle, active, error
    
    def get_status(self) -> str:
        return self.status
    
    def get_status_display(self) -> str:
        return self.status.upper()
    
    def on_input(self, msg, input_index=0):
        self.status = 'active'
        # Process message...
        self.send(msg)
```

**Frontend (nodes.js):**
```javascript
if (uiComponent === 'status-indicator') {
    const indicator = document.createElement('div');
    indicator.className = 'status-indicator status-idle';
    indicator.id = `status-${nodeData.id}`;
    indicator.textContent = 'IDLE';
    nodeContent.appendChild(indicator);
}
```

**CSS:**
```css
.status-indicator {
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 600;
    margin: 0 8px;
}

.status-idle { background: #ccc; color: #666; }
.status-active { background: #4CAF50; color: white; }
.status-error { background: #f44336; color: white; }
```

### Example 2: Progress Bar

Display processing progress:

**Node Class:**
```python
class ProcessorNode(BaseNode):
    display_name = 'Processor'
    ui_component = 'progress-bar'
    
    def __init__(self, node_id=None, name="processor"):
        super().__init__(node_id, name)
        self.progress = 0
    
    def get_progress(self) -> float:
        return self.progress
    
    def get_progress_display(self) -> str:
        return f"{int(self.progress * 100)}%"
```

**Frontend (nodes.js):**
```javascript
if (uiComponent === 'progress-bar') {
    const container = document.createElement('div');
    container.className = 'progress-container';
    
    const bar = document.createElement('div');
    bar.className = 'progress-bar';
    bar.id = `progress-${nodeData.id}`;
    bar.style.width = '0%';
    
    const text = document.createElement('span');
    text.className = 'progress-text';
    text.textContent = '0%';
    
    container.appendChild(bar);
    container.appendChild(text);
    nodeContent.appendChild(container);
}
```

**CSS:**
```css
.progress-container {
    position: relative;
    width: 60px;
    height: 18px;
    background: rgba(0, 0, 0, 0.2);
    border-radius: 3px;
    margin: 0 8px;
    overflow: hidden;
}

.progress-bar {
    height: 100%;
    background: #4CAF50;
    transition: width 0.3s;
}

.progress-text {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 10px;
    font-weight: 600;
    color: #000;
}
```

### Example 3: Multi-Button Control

Multiple action buttons on a single node:

**Node Class:**
```python
class ControlNode(BaseNode):
    display_name = 'Control'
    ui_component = 'multi-button'
    ui_component_config = {
        'buttons': [
            {'action': 'start', 'label': '▶', 'tooltip': 'Start'},
            {'action': 'pause', 'label': '⏸', 'tooltip': 'Pause'},
            {'action': 'stop', 'label': '⏹', 'tooltip': 'Stop'}
        ]
    }
    
    def start(self):
        self.state = 'running'
        return {'state': self.state}
    
    def pause(self):
        self.state = 'paused'
        return {'state': self.state}
    
    def stop(self):
        self.state = 'stopped'
        return {'state': self.state}
```

**Frontend (nodes.js):**
```javascript
if (uiComponent === 'multi-button') {
    const buttons = nodeType.ui_component_config?.buttons || [];
    
    buttons.forEach(btnConfig => {
        const btn = document.createElement('button');
        btn.className = 'control-btn';
        btn.textContent = btnConfig.label;
        btn.title = btnConfig.tooltip;
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            try {
                await fetch(`/api/nodes/${nodeData.id}/${btnConfig.action}`, {
                    method: 'POST'
                });
            } catch (error) {
                console.error(`Action ${btnConfig.action} failed:`, error);
            }
        });
        nodeContent.appendChild(btn);
    });
}
```

## Best Practices

1. **Keep components small**: UI components should fit within the node card without making it too large.

2. **Use consistent styling**: Follow the existing design patterns for buttons, displays, and colors.

3. **Handle errors gracefully**: Always wrap fetch calls in try-catch blocks.

4. **Throttle SSE updates**: Don't send updates more frequently than needed (typically 100ms minimum).

5. **Clean up resources**: Remove event listeners and close SSE connections when components are destroyed.

6. **Provide tooltips**: Use the `title` attribute or `tooltip` config for all interactive elements.

7. **Test responsiveness**: Ensure components work well when nodes are selected, dragged, or resized.

8. **Use semantic HTML**: Choose appropriate elements (button, div, span) for each component.

## Next Steps

- See [CUSTOM_NODES.md](CUSTOM_NODES.md) for complete node development guide
- See [EXTENSIBILITY.md](EXTENSIBILITY.md) for architecture details
- Examine existing nodes in `pynode/nodes/` for more examples
- Check `pynode/static/js/nodes.js` for rendering code
- Check `pynode/static/js/debug.js` for SSE handling
