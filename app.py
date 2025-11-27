"""
Flask REST API for the Node-RED-like system.
Provides endpoints for managing nodes, connections, and workflows.
"""

from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import os
import json
import time
import queue
import threading
import shutil
from datetime import datetime

from workflow_engine import WorkflowEngine
import nodes

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)  # Enable CORS for frontend

# Separate working and deployed workflow engines
# working_engine: Contains the user's current edits (not running)
# deployed_engine: Contains the deployed workflow (actually running)
working_engine = WorkflowEngine()
deployed_engine = WorkflowEngine()

# Workflow persistence file
WORKFLOW_FILE = 'workflow.json'

# Register all available node types for both engines
for engine in [working_engine, deployed_engine]:
    for node_class in nodes.get_all_node_types():
        engine.register_node_type(node_class)

# Queue for debug messages (for SSE)
debug_message_queues = {}

# Track if workflow has been loaded
workflow_loaded = False


def save_workflow_to_disk():
    """Save the current working workflow to disk with backup."""
    try:
        # Backup existing workflow if it exists
        if os.path.exists(WORKFLOW_FILE):
            # Create backup directory if it doesn't exist
            backup_dir = '_backup'
            os.makedirs(backup_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = os.path.join(backup_dir, f'workflow_{timestamp}.json')
            shutil.copy2(WORKFLOW_FILE, backup_file)
            print(f"Backed up workflow to {backup_file}")
        
        # Save new workflow
        workflow_data = working_engine.export_workflow()
        with open(WORKFLOW_FILE, 'w') as f:
            json.dump(workflow_data, f, indent=2)
        print(f"Workflow saved to {WORKFLOW_FILE}")
    except Exception as e:
        print(f"Failed to save workflow: {e}")


def load_workflow_from_disk():
    """Load workflow from disk if it exists."""
    try:
        if os.path.exists(WORKFLOW_FILE):
            with open(WORKFLOW_FILE, 'r') as f:
                workflow_data = json.load(f)
            # Load into deployed engine first (creates nodes once)
            deployed_engine.import_workflow(workflow_data)
            deployed_engine.start()  # Auto-start deployed workflow
            
            # Copy to working engine (just the data, nodes already created in deployed)
            working_engine.import_workflow(workflow_data)
            
            print(f"Loaded workflow: {len(working_engine.nodes)} nodes (deployed: running)")
        else:
            # No workflow file exists, but we still need to start the deployed engine
            # to create the system error node
            deployed_engine.start()
            print("No workflow file found, starting with empty workflow")
    except Exception as e:
        print(f"Failed to load workflow: {e}")
        # Even on error, start the deployed engine to ensure system nodes exist
        try:
            deployed_engine.start()
        except:
            pass


@app.route('/')
def index():
    """Serve the main UI."""
    return send_from_directory('static', 'index.html')


@app.route('/api/node-types', methods=['GET'])
def get_node_types():
    """Get all available node types (excluding system nodes like ErrorNode)."""
    node_types = []
    for name, node_class in working_engine.node_types.items():
        # Skip ErrorNode - it's a system node that shouldn't be manually added
        if name == 'ErrorNode':
            continue
            
        display_name = getattr(node_class, 'display_name', name)
        icon = getattr(node_class, 'icon', '◆')
        category = getattr(node_class, 'category', 'custom')
        color = getattr(node_class, 'color', '#2d2d30')
        border_color = getattr(node_class, 'border_color', '#555')
        text_color = getattr(node_class, 'text_color', '#d4d4d4')
        input_count = getattr(node_class, 'input_count', 1)
        output_count = getattr(node_class, 'output_count', 1)
        properties = getattr(node_class, 'properties', [])
        node_types.append({
            'type': name,
            'name': display_name,
            'icon': icon,
            'category': category,
            'color': color,
            'borderColor': border_color,
            'textColor': text_color,
            'inputCount': input_count,
            'outputCount': output_count,
            'properties': properties
        })
    return jsonify(node_types)


@app.route('/api/nodes', methods=['GET'])
def get_nodes():
    """Get all nodes in the working workflow."""
    nodes = []
    for node in working_engine.nodes.values():
        nodes.append(node.to_dict())
    return jsonify(nodes)


@app.route('/api/nodes', methods=['POST'])
def create_node():
    """Create a new node in working workflow."""
    data = request.json
    node_type = data.get('type')
    node_id = data.get('id')
    name = data.get('name', '')
    config = data.get('config', {})
    
    try:
        node = working_engine.create_node(node_type, node_id, name, config)
        # Set position if provided
        if 'x' in data:
            node.x = data.get('x', 0)
        if 'y' in data:
            node.y = data.get('y', 0)
        return jsonify(node.to_dict()), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/nodes/<node_id>', methods=['GET'])
def get_node(node_id):
    """Get a specific node from working workflow."""
    node = working_engine.get_node(node_id)
    if node:
        return jsonify(node.to_dict())
    return jsonify({'error': 'Node not found'}), 404


@app.route('/api/nodes/<node_id>', methods=['PUT'])
def update_node(node_id):
    """Update a node's configuration in working workflow."""
    node = working_engine.get_node(node_id)
    if not node:
        return jsonify({'error': 'Node not found'}), 404
    
    data = request.json
    
    if 'name' in data:
        node.name = data['name']
    if 'config' in data:
        node.configure(data['config'])
    if 'enabled' in data:
        node.enabled = data['enabled']
    
    return jsonify(node.to_dict())


@app.route('/api/nodes/<node_id>', methods=['DELETE'])
def delete_node(node_id):
    """Delete a node from working workflow."""
    try:
        working_engine.delete_node(node_id)
        return '', 204
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/nodes/<node_id>/position', methods=['PUT'])
def update_node_position(node_id):
    """Update a node's position in working workflow."""
    data = request.json
    try:
        node = working_engine.nodes.get(node_id)
        if not node:
            return jsonify({'error': 'Node not found'}), 404
        
        node.x = data.get('x', 0)
        node.y = data.get('y', 0)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/nodes/<node_id>/enabled', methods=['POST'])
def set_node_enabled(node_id):
    """Set node enabled state (doesn't require redeployment)."""
    data = request.json
    enabled = data.get('enabled', True)
    
    try:
        # Update BOTH working and deployed engines so state is preserved
        working_node = working_engine.nodes.get(node_id)
        deployed_node = deployed_engine.nodes.get(node_id)
        
        if working_node:
            working_node.enabled = enabled
        
        if deployed_node:
            deployed_node.enabled = enabled
        
        # Save workflow to persist the state
        save_workflow_to_disk()
        
        return jsonify({'success': True, 'enabled': enabled})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/nodes/<node_id>/enabled', methods=['GET'])
def get_node_enabled(node_id):
    """Get node enabled state."""
    try:
        # Check deployed engine first, fall back to working
        node = deployed_engine.nodes.get(node_id) or working_engine.nodes.get(node_id)
        
        if not node:
            return jsonify({'error': 'Node not found'}), 404
        
        return jsonify({'enabled': node.enabled})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/connections', methods=['POST'])
def create_connection():
    """Create a connection between two nodes in working workflow."""
    data = request.json
    source_id = data.get('source')
    target_id = data.get('target')
    source_output = data.get('sourceOutput', 0)
    target_input = data.get('targetInput', 0)
    
    try:
        working_engine.connect_nodes(source_id, target_id, source_output, target_input)
        return jsonify({
            'source': source_id,
            'target': target_id,
            'sourceOutput': source_output,
            'targetInput': target_input
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/connections', methods=['DELETE'])
def delete_connection():
    """Delete a connection between two nodes in working workflow."""
    data = request.json
    source_id = data.get('source')
    target_id = data.get('target')
    source_output = data.get('sourceOutput', 0)
    
    try:
        working_engine.disconnect_nodes(source_id, target_id, source_output)
        return '', 204
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/workflow', methods=['GET'])
def get_workflow():
    """Export the working workflow."""
    return jsonify(working_engine.export_workflow())


@app.route('/api/workflow/deployed', methods=['GET'])
def get_deployed_workflow():
    """Export the deployed workflow."""
    return jsonify(deployed_engine.export_workflow())


@app.route('/api/workflow', methods=['POST'])
def import_workflow():
    """Import a workflow into both working and deployed engines."""
    data = request.json
    try:
        deployed_engine.stop()  # Stop current deployed workflow
        working_engine.import_workflow(data)
        deployed_engine.import_workflow(data)
        save_workflow_to_disk()
        deployed_engine.start()  # Start new deployed workflow
        return jsonify(working_engine.export_workflow()), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/workflow/save', methods=['POST'])
def save_workflow():
    """Deploy the working workflow to the running engine."""
    try:
        # Export from working engine
        workflow_data = working_engine.export_workflow()
        
        # Preserve runtime state (enabled, gate state) from deployed engine
        for node_data in workflow_data.get('nodes', []):
            node_id = node_data['id']
            deployed_node = deployed_engine.nodes.get(node_id)
            
            if deployed_node:
                # Preserve enabled state (for debug nodes, gate nodes, etc.)
                node_data['enabled'] = deployed_node.enabled
        
        # Stop deployed engine and import new workflow
        deployed_engine.stop()
        deployed_engine.import_workflow(workflow_data)
        
        # Also update working engine with preserved states to keep them in sync
        working_engine.import_workflow(workflow_data)
        
        # Save to disk and start deployed engine
        save_workflow_to_disk()
        deployed_engine.start()
        
        return jsonify({'success': True}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/workflow/stats', methods=['GET'])
def get_workflow_stats():
    """Get deployed workflow statistics."""
    return jsonify(deployed_engine.get_workflow_stats())


@app.route('/api/nodes/<node_id>/inject', methods=['POST'])
def inject_node(node_id):
    """Trigger an inject node in deployed workflow."""
    try:
        deployed_engine.trigger_inject_node(node_id)
        return jsonify({'status': 'injected'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# Global message queue for SSE
debug_message_queues = {}

@app.route('/api/nodes/<node_id>/debug', methods=['GET'])
def get_debug_messages(node_id):
    """Get debug messages from a debug node in deployed workflow."""
    try:
        messages = deployed_engine.get_debug_messages(node_id)
        return jsonify(messages)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/debug/stream')
def debug_stream():
    """Server-Sent Events stream for debug messages."""
    def generate():
        # Create a queue for this client
        q = queue.Queue()
        client_id = id(q)
        debug_message_queues[client_id] = q
        
        try:
            yield 'data: {"type": "connected"}\n\n'
            
            while True:
                # Check all debug nodes in deployed workflow for new messages
                all_messages = []
                for node_id, node in deployed_engine.nodes.items():
                    if node.type == 'DebugNode':
                        # Get messages directly from the node
                        if hasattr(node, 'messages') and node.messages:
                            all_messages.extend(node.messages.copy())
                            # Clear after copying
                            node.messages.clear()
                
                # Get errors from system error node
                all_errors = deployed_engine.get_system_errors()
                
                if all_messages:
                    data = json.dumps({'type': 'messages', 'data': all_messages})
                    yield f'data: {data}\n\n'
                
                if all_errors:
                    data = json.dumps({'type': 'errors', 'data': all_errors})
                    yield f'data: {data}\n\n'
                    # Clear after sending
                    deployed_engine.clear_system_errors()
                
                # Check all image viewer nodes for frames
                for node_id, node in deployed_engine.nodes.items():
                    if node.type == 'ImageViewerNode':
                        if hasattr(node, 'get_current_frame'):
                            frame = node.get_current_frame()
                            if frame:
                                frame_data = json.dumps({
                                    'type': 'frame',
                                    'nodeId': node_id,
                                    'data': frame
                                })
                                yield f'data: {frame_data}\n\n'
                
                time.sleep(0.01)  # 10ms sleep for up to 100 FPS
        except GeneratorExit:
            # Client disconnected
            debug_message_queues.pop(client_id, None)
        except Exception as e:
            # Log error and close connection
            print(f"SSE Error: {e}")
            debug_message_queues.pop(client_id, None)
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/api/nodes/<node_id>/debug', methods=['DELETE'])
def clear_debug_messages(node_id):
    """Clear debug messages from a debug node in deployed workflow."""
    try:
        deployed_engine.clear_debug_messages(node_id)
        return '', 204
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/nodes/<node_id>/frame', methods=['GET'])
def get_image_frame(node_id):
    """Get the current frame from an image viewer node."""
    try:
        node = deployed_engine.get_node(node_id)
        if not node:
            return jsonify({'error': 'Node not found'}), 404
        
        if not hasattr(node, 'get_current_frame'):
            return jsonify({'error': 'Node does not support frame viewing'}), 400
        
        frame = node.get_current_frame()
        if frame:
            return jsonify(frame)
        else:
            return jsonify({'error': 'No frame available'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# if __name__ == '__main__':
#     # Create static directory if it doesn't exist
#     os.makedirs('static', exist_ok=True)
    
#     # Load workflow from disk on startup
#     print("Loading workflow from disk...")
#     load_workflow_from_disk()
    
#     print("Starting PyNode server...")
#     print("API available at: http://localhost:5000")
#     print("UI available at: http://localhost:5000")
    
#     app.run(debug=True, host='0.0.0.0', port=5000)
