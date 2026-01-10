# PyNode - Visual Workflow System

A Node-RED-like visual workflow editor with a Python backend. Create workflows by connecting Python nodes that process and route messages.

## Features

- **Visual Node Editor**: Drag-and-drop interface for creating workflows
- **Python Backend**: All nodes are Python classes that can be easily extended
- **Fully Extensible**: Third-party nodes can be added without modifying core code
- **UI Components**: Nodes can define interactive controls (buttons, toggles, displays) in their cards
- **Node-RED Compatible Messages**: Message structure with `payload` and `topic` fields
- **Built-in Nodes**:
  - **InjectNode**: Generate messages with configurable payloads
  - **FunctionNode**: Execute custom Python code on messages
  - **DebugNode**: Display messages in the debug panel
  - **ChangeNode**: Modify message properties
  - **SwitchNode**: Route messages based on conditions
  - **DelayNode**: Delay message delivery
  - **GateNode**: Control message flow with real-time toggle
  - **RateProbeNode**: Monitor message throughput
  - **Vision Nodes**: Camera input, YOLO detection, image processing
- **REST API**: Complete API for programmatic workflow management
- **Export/Import**: Save and load workflows as JSON
- **Dynamic Properties**: Node properties and UI components defined in node classes

## Quick Start

1. **Install PyNode**:
```bash
pip install -e .
```

2. **Run the server**:
```bash
pynode
# or
python -m pynode
```

3. **Open your browser**:
Navigate to `http://localhost:5000`

## Extending PyNode

PyNode is designed to be easily extended with custom nodes:

- **[Creating Custom Nodes](CUSTOM_NODES.md)** - Complete guide to creating your own nodes
- **[UI Components Guide](UI_COMPONENTS.md)** - Add interactive controls to your nodes
- **[Extensibility Overview](EXTENSIBILITY.md)** - Architecture and design principles

## Project Structure

```
pynode/                  # Project root
├── pynode/              # Main package
│   ├── __init__.py
│   ├── __main__.py      # Entry point for 'python -m pynode'
│   ├── main.py          # CLI application
│   ├── server.py        # Flask REST API
│   ├── workflow_engine.py  # Workflow management
│   ├── nodes/           # Node implementations (plugins)
│   │   ├── __init__.py
│   │   ├── base_node.py # BaseNode class
│   │   ├── inject_node.py
│   │   ├── function_node.py
│   │   └── ...          # Other node types
│   └── static/          # Web UI
│       ├── index.html
│       ├── style.css
│       └── app.js
├── examples/            # Example workflows
├── setup.py             # Package installation
├── requirements.txt     # Dependencies
├── README.md
└── workflow.json        # Saved workflow
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
        payload = msg[MessageKeys.PAYLOAD]
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
- `POST /api/nodes/<id>/<action>` - Trigger node action (e.g., inject, start_broadcast, etc.)

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
from pynode.workflow_engine import WorkflowEngine
from pynode.nodes import InjectNode, FunctionNode, DebugNode

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

## Development TODOs

### Completed
- ✅ Resolve SAHI splitting / joining
- ✅ Fix confidence filter node
- ✅ Draw detections clamp to the right also

### TODOs for Launch
- [ ] Update readme guides
- [ ] Update Linux setup to match Windows
- [ ] Check the inputs / outputs / arrays etc. are a standard form so nodes can be easily connected with little to no config
- [ ] Remove some nodes from standard set
- [ ] Create a new repo for extra nodes
- [ ] Queue length, like the node rate probe

### Ongoing TODOs
- [ ] Centralize more strings / constants

### Testing
- [ ] Test on Linux
- [ ] Test all nodes

### General TODOs
- [ ] Add multiple workspaces / canvases

### New Node Ideas
- [ ] OCR (PaddlePaddle)
- [ ] Qwen VLM
- [ ] REST Endpoint

### Example Flow Documentation Needed
- [ ] Bird Seed level monitor
- [ ] Capture data send to Roboflow / Geti
- [ ] Track objects time in zone
- [ ] Live VLMs
- [ ] ANPR (Detect, Crop, OCR, MQTT)

### Node-Specific TODOs
- [ ] YOLO: Add custom model support
- [ ] YOLO: Add custom target HW string
- [ ] Remove Geti node (use Roboflow instead)
- [ ] Roboflow: rfdetr
- [ ] Roboflow: upload images
- [ ] DeepSort: Add option to use different feature extractor model

## License

MIT License - Feel free to use and modify!

## Contributing

Contributions welcome! Add new node types, improve the UI, or enhance the engine.
