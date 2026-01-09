"""
PyNode - A Node-RED-like Visual Workflow System with Python Backend

This is a complete system for creating visual workflows with Python nodes.
Each node represents a function/operation and can be connected to create data pipelines.

Quick Start:
1. Install: pip install -e .
2. Run: pynode
3. Open browser: http://localhost:5000

Usage Example:
    from pynode.workflow_engine import WorkflowEngine
    from pynode.nodes import InjectNode, DebugNode
    
    engine = WorkflowEngine()
    engine.register_node_type(InjectNode)
    engine.register_node_type(DebugNode)
    
    inject = engine.create_node('InjectNode', name='my_inject')
    debug = engine.create_node('DebugNode', name='my_debug')
    engine.connect_nodes(inject.id, debug.id)
    engine.start()
"""

import argparse
import os

from pynode.server import app, load_workflow_from_disk


def main():
    """Main entry point for PyNode application."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='PyNode Visual Workflow System')
    parser.add_argument('--production', action='store_true', 
                        help='Run in production mode using Waitress server')
    parser.add_argument('--host', default='0.0.0.0', 
                        help='Host address to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=500, 
                        help='Port to bind to (default: 500)')
    args = parser.parse_args()
    
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
        print(f"For production use: pynode --production")
        app.run(debug=False, host=args.host, port=args.port, threaded=True)


if __name__ == '__main__':
    main()
