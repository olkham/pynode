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

"""

if __name__ == '__main__':
    import argparse
    import os
    from app import app, load_workflow_from_disk
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='PyNode Visual Workflow System')
    parser.add_argument('--production', action='store_true', 
                        help='Run in production mode using Waitress server')
    parser.add_argument('--host', default='0.0.0.0', 
                        help='Host address to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5000, 
                        help='Port to bind to (default: 5000)')
    args = parser.parse_args()
    
    # Create static directory if it doesn't exist
    os.makedirs('static', exist_ok=True)
    
    # Load workflow from disk on startup
    print("Loading workflow from disk...")
    load_workflow_from_disk()
    
    if args.production:
        # Production mode with Waitress
        try:
            from waitress import serve
            print(f"Starting PyNode server in PRODUCTION mode...")
            print(f"Server running at: http://{args.host}:{args.port}")
            print(f"Supports unlimited concurrent connections")
            # Use more threads for SSE connections (each tab needs 1 thread)
            # channel_timeout prevents hung connections from blocking threads
            # backlog increases queue depth for pending connections
            serve(app, host=args.host, port=args.port, threads=10, 
                  channel_timeout=120, backlog=1024, connection_limit=1000)
        except ImportError:
            print("ERROR: waitress not installed. Install with: pip install waitress")
            print("Falling back to development server...")
            app.run(debug=False, host=args.host, port=args.port, threaded=True)
    else:
        # Development mode with Flask built-in server
        print(f"Starting PyNode server in DEVELOPMENT mode...")
        print(f"Server running at: http://{args.host}:{args.port}")
        print(f"For production use: python main.py --production")
        app.run(debug=False, host=args.host, port=args.port, threaded=True)
