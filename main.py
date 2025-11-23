"""
PyNode - A Node-RED-like Visual Workflow System with Python Backend

This is a complete system for creating visual workflows with Python nodes.
Each node represents a function/operation and can be connected to create data pipelines.

Quick Start:
1. Install dependencies: pip install -r requirements.txt
2. Run the server: python main.py
3. Open browser to: http://localhost:5000

Architecture:
- base_node.py: BaseNode class that all nodes inherit from
- nodes.py: Example node implementations (Inject, Function, Debug, etc.)
- workflow_engine.py: Manages nodes, connections, and message routing
- app.py: Flask REST API for the backend
- static/: Web UI with visual node editor

Usage Example:
    from workflow_engine import WorkflowEngine
    from nodes import InjectNode, DebugNode
    
    # Create engine
    engine = WorkflowEngine()
    engine.register_node_type(InjectNode)
    engine.register_node_type(DebugNode)
    
    # Create nodes
    inject = engine.create_node('InjectNode', name='my_inject')
    debug = engine.create_node('DebugNode', name='my_debug')
    
    # Connect them
    engine.connect_nodes(inject.id, debug.id)
    
    # Start workflow
    engine.start()
    
    # Trigger inject node
    engine.trigger_inject_node(inject.id)
"""

if __name__ == '__main__':
    # Import and run the Flask app
    from app import app
    app.run(debug=False, host='0.0.0.0', port=5000)
