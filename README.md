# PyNode - Visual Workflow System

A Node-RED-like visual workflow editor with a Python backend. Create workflows by connecting Python nodes that process and route messages.

## Features

- **Visual Node Editor**: Drag-and-drop interface for creating workflows
- **Python Backend**: All nodes are Python classes that can be easily extended
- **Fully Extensible**: Third-party nodes can be added without modifying core code
- **Node-RED Compatible Messages**: Message structure with `payload` and `topic` fields
- **Built-in Nodes**:
  - **InjectNode**: Generate messages with configurable payloads
  - **FunctionNode**: Execute custom Python code on messages
  - **DebugNode**: Display messages in the debug panel
  - **ChangeNode**: Modify message properties
  - **SwitchNode**: Route messages based on conditions
  - **DelayNode**: Delay message delivery
- **REST API**: Complete API for programmatic workflow management
- **Export/Import**: Save and load workflows as JSON
- **Dynamic Properties**: Node properties defined in node classes, automatically rendered in UI

## Installation

1. **Install Python dependencies**:
```bash
pip install -r requirements.txt
```

2. **Run the server**:
```bash
python main.py
```

3. **Open your browser**:
Navigate to `http://localhost:5000`

## Project Structure

```
pynode/
├── main.py              # Application entry point
├── base_node.py         # BaseNode class (inherit from this)
├── workflow_engine.py   # Workflow management and execution
├── app.py              # Flask REST API
├── requirements.txt    # Python dependencies
├── nodes/              # Node implementations (modular)
│   ├── __init__.py
│   ├── inject_node.py
│   ├── function_node.py
│   ├── debug_node.py
│   ├── change_node.py
│   ├── switch_node.py
│   ├── delay_node.py
│   └── template_node.py  # Example custom node
├── static/
│   ├── index.html      # Web UI
│   ├── style.css       # Styling
│   └── app.js          # Frontend JavaScript
├── README.md           # This file
└── CUSTOM_NODES.md     # Guide for creating custom nodes
```

## Creating Custom Nodes

PyNode is fully extensible! All node information (visual properties, property schemas, behavior) is contained within the node class itself. The main application has no hardcoded knowledge of specific node types.

For a complete guide, see [CUSTOM_NODES.md](CUSTOM_NODES.md)

Here's a simple example:

```python
from base_node import BaseNode

class MyCustomNode(BaseNode):
    """Example custom node."""
    
    # Visual properties
    category = 'custom'
    color = '#FFA07A'
    border_color = '#FF7F50'
    text_color = '#000000'
    
    # Property schema (appears in UI)
    properties = [
        {
            'name': 'multiplier',
            'label': 'Multiplier',
            'type': 'text'
        }
    ]
    
    def __init__(self, node_id=None, name="custom"):
        super().__init__(node_id, name)
        self.configure({
            'multiplier': 2
        })
    
    def on_input(self, msg, input_index=0):
        # Process the incoming message
        payload = msg['payload']
        multiplier = float(self.config.get('multiplier', 2))
        
        # Modify the payload
        new_payload = payload * multiplier
        
        # Create and send new message
        new_msg = self.create_message(
            payload=new_payload,
            topic=msg.get('topic', '')
        )
        self.send(new_msg)

# Register your node in app.py
from nodes import MyCustomNode
engine.register_node_type(MyCustomNode)
```

## Message Structure

Messages follow the Node-RED format:

```python
{
    'payload': 'any data type',  # The main message content
    'topic': 'string',            # Optional topic/category
    '_msgid': 'unique-id',        # Auto-generated message ID
    # ... any additional properties
}
```

## API Endpoints

### Nodes
- `GET /api/nodes` - List all nodes
- `POST /api/nodes` - Create a node
- `GET /api/nodes/<id>` - Get node details
- `PUT /api/nodes/<id>` - Update node
- `DELETE /api/nodes/<id>` - Delete node
- `POST /api/nodes/<id>/inject` - Trigger inject node

### Connections
- `POST /api/connections` - Create connection
- `DELETE /api/connections` - Delete connection

### Workflow
- `GET /api/workflow` - Export workflow
- `POST /api/workflow` - Import workflow
- `POST /api/workflow/start` - Start workflow
- `POST /api/workflow/stop` - Stop workflow
- `GET /api/workflow/stats` - Get statistics

### Debug
- `GET /api/nodes/<id>/debug` - Get debug messages
- `DELETE /api/nodes/<id>/debug` - Clear debug messages

## Example Programmatic Usage

```python
from workflow_engine import WorkflowEngine
from nodes import InjectNode, FunctionNode, DebugNode

# Create and configure engine
engine = WorkflowEngine()
engine.register_node_type(InjectNode)
engine.register_node_type(FunctionNode)
engine.register_node_type(DebugNode)

# Create nodes
inject = engine.create_node('InjectNode', name='source')
inject.configure({'payload': 10, 'payloadType': 'num'})

func = engine.create_node('FunctionNode', name='multiply')
func.configure({'func': 'msg["payload"] = msg["payload"] * 2\nreturn msg'})

debug = engine.create_node('DebugNode', name='output')

# Connect nodes: inject -> function -> debug
engine.connect_nodes(inject.id, func.id)
engine.connect_nodes(func.id, debug.id)

# Start and trigger
engine.start()
engine.trigger_inject_node(inject.id)

# Check debug output
messages = engine.get_debug_messages(debug.id)
print(messages)  # Should show payload=20
```

## Web UI Usage

1. **Add Nodes**: Drag nodes from the palette onto the canvas
2. **Connect Nodes**: Click on an output port (right side) and drag to an input port (left side)
3. **Configure Nodes**: Click a node to show its properties panel
4. **Test Workflow**: 
   - Click "Start" to activate the workflow
   - Use "Inject" button on inject nodes to send messages
   - View output in the debug panel at the bottom
5. **Save/Load**: Use Export/Import buttons to save workflows

## Extending the System

### Adding New Node Types

1. Create a new class in `nodes.py` or a new file
2. Inherit from `BaseNode`
3. Override `on_input()` for message processing
4. Register the node type in `app.py`

### Custom Message Processing

Nodes can:
- Modify message payload
- Add/remove message properties
- Send to multiple outputs
- Send multiple messages
- Filter messages
- Store state between messages

### Advanced Features

- **Background Processing**: Use threading for long-running operations
- **External APIs**: Make HTTP requests from function nodes
- **Database Integration**: Store/retrieve data from databases
- **File I/O**: Read/write files in custom nodes
- **Scheduling**: Implement timed node execution

## License

MIT License - Feel free to use and modify!

## Contributing

Contributions welcome! Add new node types, improve the UI, or enhance the engine.
