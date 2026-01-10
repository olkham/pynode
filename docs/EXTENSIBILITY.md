# Extensibility and Architecture

This document explains PyNode's architecture and extensibility features. PyNode is designed from the ground up to be extended with custom nodes without modifying core code.

## Table of Contents

- [Core Principles](#core-principles)
- [Architecture Overview](#architecture-overview)
- [Node Discovery](#node-discovery)
- [Message Flow](#message-flow)
- [Workflow Engine](#workflow-engine)
- [REST API](#rest-api)
- [Frontend Architecture](#frontend-architecture)
- [Extension Points](#extension-points)

## Core Principles

### 1. Node Self-Description

All node information is contained within the node class itself:

- **Visual Properties**: Colors, icons, display names
- **I/O Configuration**: Number of inputs and outputs
- **Property Schema**: UI form fields and validation
- **Documentation**: Built-in help and examples
- **Behavior**: Message processing logic

The core application has **zero hardcoded knowledge** of specific node types. Everything is discovered at runtime.

### 2. Plugin Architecture

Nodes are organized in individual folders within `pynode/nodes/`:

```
nodes/
├── base_node.py          # Base class
├── MyNode/
│   ├── __init__.py       # Exports node class
│   ├── my_node.py        # Implementation
│   ├── requirements.txt  # Dependencies (optional)
│   └── README.md         # Docs (optional)
└── AnotherNode/
    └── ...
```

Each node folder is a self-contained plugin that can be:
- Added without modifying core code
- Distributed separately
- Installed/removed independently
- Version-controlled separately

### 3. Message-Based Communication

Nodes communicate through messages following the Node-RED format:

```python
{
    'payload': Any,           # Primary data
    'topic': str,             # Optional categorization
    '_msgid': str,            # Unique identifier
    '_queue_length': int,     # Queue depth (added by engine)
    # ... any additional fields
}
```

This loose coupling allows any node to connect to any other node, regardless of their specific types.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                        Web Browser                           │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │   Canvas   │  │  Properties  │  │   Debug Panel      │    │
│  │  (Nodes +  │  │    Panel     │  │ (Message output)   │    │
│  │Connections)│  │              │  │                    │    │
│  └────────────┘  └──────────────┘  └────────────────────┘    │
│                           │                                  │
│                     REST API + SSE                           │
└───────────────────────────┼──────────────────────────────────┘
                            │
┌───────────────────────────┼──────────────────────────────────┐
│                      Flask Server                            │
│  ┌──────────────────┐     │   ┌──────────────────────────┐   │
│  │   server.py      │◄────┴──►│   workflow_engine.py     │   │
│  │  (REST + SSE)    │         │  (Execution engine)      │   │
│  └──────────────────┘         └─────────────┬────────────┘   │
│                                             │                │
│                                             │                │
│  ┌──────────────────────────────────────────┴──────────────┐ │
│  │                    Node Instances                       │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐  │ │
│  │  │InjectNode│─►│Function  │─►│DebugNode │  │ Camera  │  │ │
│  │  │          │  │   Node   │  │          │  │  Node   │  │ │
│  │  └──────────┘  └──────────┘  └──────────┘  └─────────┘  │ │
│  │         Each runs in its own worker thread              │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

## Node Discovery

### Registration Process

1. **Import**: The workflow engine imports all folders from `pynode/nodes/`
2. **Instantiation**: Each node class is instantiated to read metadata
3. **Introspection**: The engine reads visual properties, I/O config, and property schema
4. **Type Registration**: Node type is registered with metadata
5. **Frontend Sync**: Node types are sent to frontend via `/api/node-types`

### Discovery Code

From `workflow_engine.py`:

```python
def _discover_nodes(self):
    """Discover and register all node types."""
    nodes_dir = Path(__file__).parent / 'nodes'
    
    for item in nodes_dir.iterdir():
        if item.is_dir() and not item.name.startswith('_'):
            try:
                # Import the module
                module = importlib.import_module(f'pynode.nodes.{item.name}')
                
                # Find BaseNode subclasses
                for name, obj in inspect.getmembers(module):
                    if (inspect.isclass(obj) and 
                        issubclass(obj, BaseNode) and 
                        obj is not BaseNode):
                        self.register_node_type(obj)
            except Exception as e:
                print(f"Error loading node {item.name}: {e}")
```

### Metadata Extraction

```python
def register_node_type(self, node_class):
    """Register a node type with the engine."""
    # Create temporary instance to read metadata
    temp_instance = node_class()
    
    metadata = {
        'type': node_class.__name__,
        'name': getattr(node_class, 'display_name', node_class.__name__),
        'category': getattr(node_class, 'category', 'general'),
        'color': getattr(node_class, 'color', '#999999'),
        'icon': getattr(node_class, 'icon', '⬢'),
        'inputCount': getattr(node_class, 'input_count', 1),
        'outputCount': getattr(node_class, 'output_count', 1),
        'properties': getattr(node_class, 'properties', []),
        'info': getattr(node_class, 'info', ''),
        # ... more metadata
    }
    
    self.node_types[node_class.__name__] = {
        'class': node_class,
        'metadata': metadata
    }
```

## Message Flow

### Asynchronous Processing

Each node runs in its own worker thread with a message queue:

```python
class BaseNode:
    def __init__(self, node_id=None, name=""):
        # Message queue (non-blocking)
        self._message_queue = queue.Queue(maxsize=1000)
        self._worker_thread = None
        self._processing = False
        
    def start(self):
        """Start the worker thread."""
        self._stop_worker_flag = False
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True
        )
        self._worker_thread.start()
    
    def _worker_loop(self):
        """Worker thread that processes messages."""
        while not self._stop_worker_flag:
            try:
                msg, input_idx = self._message_queue.get(timeout=0.1)
                self._processing = True
                
                # Call user-defined processing
                self.on_input(msg, input_idx)
                
                self._processing = False
            except queue.Empty:
                continue
            except Exception as e:
                self.report_error(str(e))
```

### Queue Management

Messages are enqueued with optional dropping:

```python
def receive(self, msg: Dict[str, Any], input_index: int = 0):
    """Receive a message on an input."""
    if not self.enabled:
        return
    
    # Add queue length metadata
    msg[MessageKeys.QUEUE_LENGTH] = self._message_queue.qsize()
    
    try:
        if self.drop_while_busy and self._processing:
            # Drop message if node is busy
            self.drop_count += 1
            return
        
        # Enqueue message (blocks if queue is full)
        self._message_queue.put((deepcopy(msg), input_index))
    except queue.Full:
        self.drop_count += 1
```

### Connection Routing

Messages are routed through connections:

```python
def send(self, msg: Dict[str, Any], output_index: int = 0):
    """Send a message to connected nodes."""
    if output_index not in self.outputs:
        return
    
    # Get all connections from this output
    connections = self.outputs[output_index]
    
    # Send to each connected node
    for target_node, target_input_index in connections:
        # Deep copy to prevent shared state
        msg_copy = deepcopy(msg)
        target_node.receive(msg_copy, target_input_index)
```

## Workflow Engine

### Engine Responsibilities

The `WorkflowEngine` class manages:

1. **Node Lifecycle**: Creating, starting, stopping nodes
2. **Connections**: Establishing links between nodes
3. **Type Registry**: Maintaining available node types
4. **State Management**: Workflow running/stopped state
5. **Error Handling**: Broadcasting errors to ErrorNodes

### Node Creation

```python
def create_node(self, node_type: str, node_id: str = None, 
                name: str = None, config: Dict = None):
    """Create a node instance."""
    if node_type not in self.node_types:
        raise ValueError(f"Unknown node type: {node_type}")
    
    # Instantiate node
    node_class = self.node_types[node_type]['class']
    node = node_class(node_id=node_id, name=name)
    
    # Set workflow engine reference
    node.set_workflow_engine(self)
    
    # Apply configuration
    if config:
        node.configure(config)
    
    # Register node
    self.nodes[node.id] = node
    
    return node
```

### Connection Management

```python
def connect_nodes(self, source_id: str, target_id: str,
                  output_index: int = 0, input_index: int = 0):
    """Connect two nodes."""
    source = self.nodes.get(source_id)
    target = self.nodes.get(target_id)
    
    if not source or not target:
        raise ValueError("Invalid node IDs")
    
    # Create connection
    source.connect(target, output_index, input_index)
    
    # Track in engine
    self.connections.append({
        'source': source_id,
        'target': target_id,
        'sourceOutput': output_index,
        'targetInput': input_index
    })
```

### Starting/Stopping

```python
def start(self):
    """Start all nodes in the workflow."""
    if self.running:
        return
    
    self.running = True
    
    # Start each node's worker thread
    for node in self.nodes.values():
        try:
            node.start()
        except Exception as e:
            print(f"Error starting {node.name}: {e}")

def stop(self):
    """Stop all nodes in the workflow."""
    if not self.running:
        return
    
    self.running = False
    
    # Stop each node's worker thread
    for node in self.nodes.values():
        try:
            node.stop()
        except Exception as e:
            print(f"Error stopping {node.name}: {e}")
```

## REST API

### Endpoint Organization

The Flask server exposes a REST API organized by resource:

- `/api/nodes` - Node CRUD operations
- `/api/connections` - Connection management
- `/api/workflow` - Workflow control and serialization
- `/api/node-types` - Available node types (for palette)
- `/api/events` - Server-Sent Events stream

### Node Actions

Dynamic actions based on node methods:

```python
@app.route('/api/nodes/<node_id>/<action>', methods=['POST'])
def node_action(node_id, action):
    """Trigger a node action."""
    node = engine.nodes.get(node_id)
    if not node:
        return jsonify({'error': 'Node not found'}), 404
    
    # Check if node has this method
    if not hasattr(node, action):
        return jsonify({'error': f'Action {action} not found'}), 404
    
    # Call the method
    try:
        method = getattr(node, action)
        result = method()
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

### Workflow Serialization

Export/import workflows as JSON:

```python
@app.route('/api/workflow', methods=['GET'])
def get_workflow():
    """Export current workflow."""
    nodes = [
        {
            'id': node.id,
            'type': node.type,
            'name': node.name,
            'config': node.config,
            'x': node.x,  # Position
            'y': node.y
        }
        for node in engine.nodes.values()
    ]
    
    connections = engine.connections
    
    return jsonify({
        'nodes': nodes,
        'connections': connections
    })

@app.route('/api/workflow', methods=['POST'])
def load_workflow():
    """Import a workflow."""
    data = request.json
    
    # Clear current workflow
    engine.clear()
    
    # Create nodes
    for node_data in data.get('nodes', []):
        engine.create_node(
            node_type=node_data['type'],
            node_id=node_data['id'],
            name=node_data['name'],
            config=node_data.get('config', {})
        )
    
    # Create connections
    for conn in data.get('connections', []):
        engine.connect_nodes(
            conn['source'],
            conn['target'],
            conn.get('sourceOutput', 0),
            conn.get('targetInput', 0)
        )
    
    return jsonify({'success': True})
```

## Frontend Architecture

### Module Organization

JavaScript is organized into modules:

- `nodes.js` - Node rendering and management
- `connections.js` - Wire drawing and interaction
- `events.js` - User input handling
- `debug.js` - Debug panel and SSE
- `history.js` - Undo/redo system
- `palette.js` - Node palette
- `properties.js` - Properties panel

### State Management

Global state object tracks everything:

```javascript
const state = {
    nodes: new Map(),           // Node instances
    connections: new Map(),     // Wire connections
    selectedNodes: new Set(),   // Selected node IDs
    clipboard: null,            // Copy/paste buffer
    panOffset: { x: 0, y: 0 }, // Canvas pan
    zoom: 1.0,                  // Canvas zoom
    isDragging: false,          // Drag state
    // ... more state
};
```

### Node Rendering

Dynamic rendering based on node type:

```javascript
export function renderNode(nodeData) {
    const nodeEl = document.createElement('div');
    nodeEl.className = 'node';
    nodeEl.id = `node-${nodeData.id}`;
    
    // Apply visual properties
    nodeEl.style.backgroundColor = nodeData.color;
    nodeEl.style.borderColor = nodeData.borderColor;
    nodeEl.style.color = nodeData.textColor;
    
    // Render icon
    const icon = document.createElement('div');
    icon.className = 'node-icon';
    icon.textContent = nodeData.icon;
    nodeEl.appendChild(icon);
    
    // Render UI component (if any)
    const nodeType = getNodeType(nodeData.type);
    const uiComponent = nodeType?.ui_component;
    
    if (uiComponent) {
        renderUIComponent(nodeEl, uiComponent, nodeData, nodeType);
    }
    
    // Render ports
    renderPorts(nodeEl, nodeData);
    
    // Add to canvas
    canvas.appendChild(nodeEl);
}
```

### Property Panel

Dynamic form generation:

```javascript
function renderProperties(nodeData) {
    const nodeType = getNodeType(nodeData.type);
    const properties = nodeType?.properties || [];
    
    properties.forEach(prop => {
        switch (prop.type) {
            case 'text':
                renderTextInput(prop, nodeData);
                break;
            case 'number':
                renderNumberInput(prop, nodeData);
                break;
            case 'select':
                renderSelect(prop, nodeData);
                break;
            case 'checkbox':
                renderCheckbox(prop, nodeData);
                break;
            // ... more types
        }
    });
}
```

## Extension Points

### 1. Custom Node Types

Create new node types by extending `BaseNode`:

```python
from pynode.nodes.base_node import BaseNode

class MyExtension(BaseNode):
    # Define all node properties
    display_name = 'My Extension'
    # ... implementation
```

Place in `pynode/nodes/MyExtension/` for auto-discovery.

### 2. UI Components

Add custom UI components:

1. Define `ui_component` in node class
2. Add rendering code to `nodes.js`
3. Add styling to `style.css`
4. Add SSE handlers to `debug.js` (if needed)

### 3. Message Properties

Add custom message properties:

```python
msg['_custom_field'] = 'custom data'
```

Any node can read/write custom fields. Use underscore prefix for metadata.

### 4. Node Dependencies

Include a `requirements.txt` in the node folder:

```
pynode/nodes/MyNode/
├── requirements.txt
└── my_node.py
```

The installer will handle node-specific dependencies.

### 5. Error Handling

Custom error reporting:

```python
def on_input(self, msg, input_index=0):
    try:
        # Process message
        result = risky_operation(msg)
    except Exception as e:
        # Report to ErrorNodes
        self.report_error(f"Operation failed: {e}")
```

ErrorNodes in the workflow will receive error messages.

## Best Practices

1. **Avoid Core Modifications**: Extend through plugins, not by modifying core files
2. **Use MessageKeys**: Import constants instead of hardcoding strings
3. **Document Extensions**: Include README and Info documentation
4. **Handle Errors**: Always use try-except and report errors
5. **Thread Safety**: Be careful with shared state between threads
6. **Test Isolation**: Ensure nodes work independently
7. **Version Dependencies**: Pin versions in requirements.txt
8. **Follow Conventions**: Match existing code style and patterns

## Further Reading

- [CUSTOM_NODES.md](CUSTOM_NODES.md) - Node development guide
- [UI_COMPONENTS.md](UI_COMPONENTS.md) - UI component guide
- Source code in `pynode/` directory
- Example nodes in `pynode/nodes/`
