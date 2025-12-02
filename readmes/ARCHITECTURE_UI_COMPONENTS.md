# UI Component Architecture

This document explains how the UI component system works internally, for developers who want to understand or extend the system.

## Architecture Overview

The UI component system uses a **declarative approach** where nodes define what UI they want, and the frontend renders it based on component type.

### Flow

```
Node Class (Python)          API Response              Frontend Rendering
┌──────────────────┐        ┌──────────────┐         ┌──────────────────┐
│ ui_component =   │        │ "uiComponent"│         │ buildNodeContent │
│   'button'       │───────>│  'button'    │────────>│ renders button   │
│ ui_component_    │        │ "uiConfig": {│         │ with onclick     │
│   config = {...} │        │   ...        │         │ handler          │
└──────────────────┘        └──────────────┘         └──────────────────┘
```

## Backend Components

### 1. BaseNode Class Properties

**File:** `base_node.py`

```python
class BaseNode:
    ui_component = None  # Component type: 'button', 'toggle', 'rate-display'
    ui_component_config = {}  # Component-specific configuration
```

These class attributes are read by the API endpoint and sent to the frontend.

### 2. API Endpoint

**File:** `app.py` - `/api/node-types`

```python
@app.route('/api/node-types', methods=['GET'])
def get_node_types():
    # ... for each node type ...
    ui_component = getattr(node_class, 'ui_component', None)
    ui_component_config = getattr(node_class, 'ui_component_config', {})
    
    node_types.append({
        # ... other properties ...
        'uiComponent': ui_component,
        'uiComponentConfig': ui_component_config
    })
```

This endpoint is called once on page load and cached in the frontend state.

### 3. Generic Action Handler

**File:** `app.py` - `/api/nodes/<node_id>/<action>`

```python
@app.route('/api/nodes/<node_id>/<action>', methods=['POST'])
def trigger_node_action(node_id, action):
    node = deployed_engine.get_node(node_id)
    method = getattr(node, action)
    if callable(method):
        method()  # Call the node's action method
```

This generic endpoint handles all button actions by calling the corresponding method on the node instance.

## Frontend Components

### 1. State Management

**File:** `static/js/state.js`

```javascript
export const state = {
    nodeTypes: [],           // Full node type metadata from API
    nodeTypesMap: new Map(), // Fast lookup: type name -> metadata
    nodes: new Map(),        // Active nodes in workflow
    // ...
};

export function setNodeTypes(types) {
    state.nodeTypes = types;
    state.nodeTypesMap.clear();
    types.forEach(nt => state.nodeTypesMap.set(nt.type, nt));
}
```

Node type metadata (including UI component info) is fetched once and cached.

### 2. Node Rendering

**File:** `static/js/nodes.js`

```javascript
function buildNodeContent(nodeData, icon, inputCount, outputCount) {
    const nodeType = getNodeType(nodeData.type);
    const uiComponent = nodeType?.uiComponent;
    const uiConfig = nodeType?.uiComponentConfig || {};
    
    // Build HTML based on component type
    if (uiComponent === 'button') {
        // Create button with action handler
    } else if (uiComponent === 'toggle') {
        // Create toggle switch
    } else if (uiComponent === 'rate-display') {
        // Create display element
    }
}
```

The function dynamically generates HTML based on the component type from the node's metadata.

### 3. Action Handler

**File:** `static/js/nodes.js`

```javascript
window.nodeAction = async function(nodeId, action, value) {
    if (action === 'inject') {
        await fetch(`${API_BASE}/nodes/${nodeId}/inject`, { method: 'POST' });
    } else if (action === 'toggle_gate') {
        await window.toggleGate(nodeId, value);
    } else {
        // Generic action
        await fetch(`${API_BASE}/nodes/${nodeId}/${action}`, { method: 'POST' });
    }
};
```

This unified handler routes actions to the appropriate backend endpoint.

## Component Types

### Button Component

**HTML Generated:**
```html
<button class="inject-btn" 
        onclick="window.nodeAction('node_123', 'reset_counter')" 
        title="Reset">
    ↻
</button>
```

**CSS Classes:** `.inject-btn` (styled in `static/style.css`)

**Config Options:**
- `icon` - Character/emoji shown in button
- `action` - Method name to call on node
- `tooltip` - Hover text

### Toggle Component

**HTML Generated:**
```html
<label class="gate-switch">
    <input type="checkbox" id="toggle-node_123" checked 
           onchange="window.nodeAction('node_123', 'toggle_gate', this.checked)">
    <span class="gate-slider"></span>
</label>
```

**CSS Classes:** `.gate-switch`, `.gate-slider` (styled in `static/style.css`)

**Config Options:**
- `action` - Action name for toggle
- `label` - Optional label text

**State Management:**
The toggle state is synced with the node's `enabled` property via the `/api/nodes/<id>/enabled` endpoint.

### Rate Display Component

**HTML Generated:**
```html
<div class="rate-display" id="rate-node_123">0/s</div>
```

**CSS Classes:** `.rate-display` (styled in `static/style.css`)

**Config Options:**
- `format` - Display format string (e.g., `{value}/s`)
- `precision` - Number of decimal places

**Updates:**
Updated via SSE (Server-Sent Events) when the node sends messages containing rate information.

## Adding New Component Types

To add a new component type (e.g., `slider`):

### 1. Update BaseNode Documentation

Add the new type to `base_node.py` docstring:

```python
# UI Component for custom node controls
# Options: None, 'button', 'toggle', 'rate-display', 'slider'
```

### 2. Update Frontend Rendering

Add case in `static/js/nodes.js`:

```javascript
else if (uiComponent === 'slider') {
    const min = uiConfig.min || 0;
    const max = uiConfig.max || 100;
    const value = nodeData[uiConfig.property] || 50;
    contentParts.right = `
        <input type="range" min="${min}" max="${max}" value="${value}"
               oninput="window.nodeAction('${nodeData.id}', '${uiConfig.action}', this.value)">
    `;
}
```

### 3. Add CSS Styling

Add styles in `static/style.css`:

```css
.node-slider {
    width: 80px;
    margin: 0 8px;
}
```

### 4. Document It

Update `UI_COMPONENTS.md` with usage examples.

## Design Principles

### 1. Declarative Over Imperative

Nodes **declare what they want** rather than how to build it:
```python
ui_component = 'button'  # What
```

Not:
```python
html = '<button>...</button>'  # How (bad)
```

### 2. Type Safety

Limited set of component types prevents:
- XSS attacks (no arbitrary HTML)
- Inconsistent UI
- Maintenance nightmares

### 3. Separation of Concerns

- **Backend**: Defines intent and handles actions
- **Frontend**: Handles rendering and user interaction
- **CSS**: Handles styling

### 4. Backwards Compatibility

Nodes without `ui_component` render with default layout. No breaking changes for existing nodes.

## Security Considerations

### No Arbitrary HTML

The system does NOT allow nodes to inject arbitrary HTML:
```python
# This would be DANGEROUS (not supported):
ui_html = '<script>alert("XSS")</script>'
```

Instead, use predefined component types that are safely rendered by the frontend.

### Action Method Security

Action handlers call methods that exist on the node instance. Non-existent methods return 404.

### State Validation

Toggle states are validated on the backend. The frontend is just a view.

## Performance Considerations

### Metadata Caching

Node type metadata (including UI component info) is fetched once and cached:
- Reduces API calls
- Faster node rendering
- Enables offline palette

### Event Delegation

Could use event delegation for better performance with many nodes:
```javascript
// Future optimization
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('inject-btn')) {
        const nodeId = e.target.dataset.nodeId;
        // Handle action
    }
});
```

### SSE for Updates

Rate displays use Server-Sent Events rather than polling:
- Lower latency
- Less server load
- Real-time updates

## Testing Strategy

### Unit Tests (Future)

```python
def test_ui_component_metadata():
    """Test that UI component metadata is correctly exposed"""
    from nodes.InjectNode import InjectNode
    assert InjectNode.ui_component == 'button'
    assert InjectNode.ui_component_config['action'] == 'inject'
```

### Integration Tests (Future)

```javascript
describe('Node UI Components', () => {
    it('should render button for InjectNode', () => {
        const node = createNode('InjectNode', 100, 100);
        const button = node.querySelector('.inject-btn');
        expect(button).toBeTruthy();
    });
});
```

## Future Enhancements

### Planned Component Types

1. **Dropdown** - Select from options inline
2. **Badge** - Show status with color
3. **Sparkline** - Mini time-series chart
4. **Progress Bar** - Show completion percentage
5. **Color Picker** - Visual color selection

### Composite Components

Allow combining multiple components:
```python
ui_components = [
    {'type': 'button', 'config': {...}},
    {'type': 'rate-display', 'config': {...}}
]
```

### Custom Styling

Allow nodes to override component styles:
```python
ui_component_config = {
    'type': 'button',
    'icon': '▶',
    'style': {
        'background': '#ff0000',
        'color': '#ffffff'
    }
}
```

### React/Vue Component Support

For complex UIs, support custom React/Vue components:
```python
ui_component = 'custom'
ui_component_bundle = 'path/to/component.js'
```

This would require a plugin system and sandboxing.
