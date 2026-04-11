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

from pynode.workflow_engine import WorkflowEngine
from pynode import nodes

# Set the base directory for project root (for workflow.json)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Package directory (for static files)
PKG_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder=os.path.join(PKG_DIR, 'static'), static_url_path='')
CORS(app)  # Enable CORS for frontend

# Separate working and deployed workflow engines
# working_engine: Contains the user's current edits (not running)
# deployed_engine: Contains the deployed workflow (actually running)
working_engine = WorkflowEngine()
deployed_engine = WorkflowEngine()

# Workflow persistence directories and files
WORKFLOWS_DIR = os.path.join(BASE_DIR, 'workflows')
WORKFLOW_FILE = os.path.join(WORKFLOWS_DIR, 'workflow.json')

# Ensure workflows directory exists
os.makedirs(WORKFLOWS_DIR, exist_ok=True)

# Register all available node types for both engines
for engine in [working_engine, deployed_engine]:
    for node_class in nodes.get_all_node_types():
        engine.register_node_type(node_class)

# Cache for node types (built once at startup or on first request)
_node_types_cache = None

def _build_node_types_cache():
    """Build the node types cache from registered node types."""
    global _node_types_cache
    
    from pynode.nodes.base_node import BaseNode
    base_properties = getattr(BaseNode, 'properties', [])
    
    # Define category ordering
    category_order = [
        'common',
        'node probes',
        'logic',
        'function',
        'input',
        'output',
        'vision',
        'analysis',        
        'network',
        'OpenCV'
    ]
    
    node_types = []
    for name, node_class in working_engine.node_types.items():
        # Skip ErrorNode - it's a system node that shouldn't be manually added
        if node_class.hidden:
            continue
            
        display_name = getattr(node_class, 'display_name', name)
        icon = getattr(node_class, 'icon', '◆')
        category = getattr(node_class, 'category', 'custom')
        color = getattr(node_class, 'color', '#2d2d30')
        border_color = getattr(node_class, 'border_color', '#555')
        text_color = getattr(node_class, 'text_color', '#d4d4d4')
        input_count = getattr(node_class, 'input_count', 1)
        output_count = getattr(node_class, 'output_count', 1)
        
        # Handle callable properties (get_properties classmethod)
        if hasattr(node_class, 'get_properties') and callable(node_class.get_properties):
            node_properties = node_class.get_properties()
        else:
            node_properties = getattr(node_class, 'properties', [])
        
        # Ensure node_properties is iterable (list or tuple)
        if not isinstance(node_properties, (list, tuple)):
            node_properties = []
        
        # Get property names from node-specific properties to avoid duplicates
        node_prop_names = {prop.get('name') for prop in node_properties if isinstance(prop, dict)}
        
        # Add base properties that aren't overridden by node-specific properties
        merged_properties = [prop for prop in base_properties if prop.get('name') not in node_prop_names]
        # Add all node-specific properties
        merged_properties.extend(node_properties)
        
        ui_component = getattr(node_class, 'ui_component', None)
        ui_component_config = getattr(node_class, 'ui_component_config', {})
        info = getattr(node_class, 'info', '')
        
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
            'properties': merged_properties,
            'uiComponent': ui_component,
            'uiComponentConfig': ui_component_config,
            'info': info
        })
    
    # Sort node types by category order, then by name within each category
    def get_category_sort_key(node_type):
        category = node_type['category']
        try:
            # Categories in the order list get their index
            order_index = category_order.index(category)
        except ValueError:
            # Categories not in the list go to the end (third party)
            order_index = len(category_order)
        return (order_index, node_type['name'])
    
    node_types.sort(key=get_category_sort_key)
    
    _node_types_cache = node_types
    return _node_types_cache

# Build cache at startup
_build_node_types_cache()

# ==============================================================================
# Dynamic Node Endpoint and SSE Registration
# ==============================================================================

# Build a registry of node types that have SSE handlers
# Maps node_type_name -> list of sse_handler defs
_sse_handler_registry = {}

# Build a registry of node types that have api_routes
# Maps node_type_name -> list of route defs  
_api_route_registry = {}

def _build_node_registries():
    """Scan all node classes and build registries for API routes and SSE handlers."""
    for node_class in nodes.get_all_node_types():
        node_type_name = node_class.__name__
        
        api_routes = getattr(node_class, 'api_routes', [])
        if api_routes:
            _api_route_registry[node_type_name] = api_routes
        
        sse_handlers = getattr(node_class, 'sse_handlers', [])
        if sse_handlers:
            _sse_handler_registry[node_type_name] = sse_handlers

_build_node_registries()


def _register_dynamic_node_routes():
    """Register Flask routes for all node types that declare api_routes."""
    registered = set()
    
    for node_type_name, routes in _api_route_registry.items():
        for route_def in routes:
            route = route_def['route']
            methods = route_def.get('methods', ['GET'])
            handler_name = route_def['handler']
            route_type = route_def.get('type', 'json')
            
            # Create a unique endpoint name for Flask
            # Combine methods to handle same route with different methods
            methods_key = '_'.join(sorted(methods))
            endpoint_name = f"node_{node_type_name}_{route}_{methods_key}"
            
            if endpoint_name in registered:
                continue
            registered.add(endpoint_name)
            
            if route_type == 'file_upload':
                allowed_ext = route_def.get('allowed_extensions', set())
                _register_file_upload_route(route, methods, handler_name, endpoint_name, allowed_ext)
            elif route_type == 'stream':
                _register_stream_route(route, handler_name, endpoint_name)
            else:
                _register_json_route(route, methods, handler_name, endpoint_name)


def _register_json_route(route, methods, handler_name, endpoint_name):
    """Register a standard JSON API route."""
    def handler(node_id):
        node = deployed_engine.get_node(node_id)
        if not node:
            return jsonify({'error': 'Node not found'}), 404
        
        method = getattr(node, handler_name, None)
        if method is None or not callable(method):
            return jsonify({'error': f'Node does not support {handler_name}'}), 400
        
        try:
            result = method()
            if result is None:
                return '', 204
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    app.add_url_rule(
        f'/api/nodes/<node_id>/{route}',
        endpoint=endpoint_name,
        view_func=handler,
        methods=methods
    )


def _register_file_upload_route(route, methods, handler_name, endpoint_name, allowed_extensions):
    """Register a file upload API route."""
    def handler(node_id):
        node = deployed_engine.get_node(node_id)
        if not node:
            return jsonify({'success': False, 'error': 'Node not found'}), 404
        
        method = getattr(node, handler_name, None)
        if method is None or not callable(method):
            return jsonify({'success': False, 'error': f'Node does not support {handler_name}'}), 400
        
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        if not file.filename or file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        if allowed_extensions:
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in allowed_extensions:
                return jsonify({'success': False, 'error': f'Unsupported file type: {ext}'}), 400
        
        try:
            file_bytes = file.read()
            result = method(file_bytes, file.filename)
            return jsonify(result)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500
    
    app.add_url_rule(
        f'/api/nodes/<node_id>/{route}',
        endpoint=endpoint_name,
        view_func=handler,
        methods=methods
    )


def _register_stream_route(route, handler_name, endpoint_name):
    """Register an MJPEG stream route."""
    def handler(node_id):
        node = deployed_engine.get_node(node_id)
        if not node:
            return jsonify({'error': 'Node not found'}), 404
        
        method = getattr(node, handler_name, None)
        if method is None or not callable(method):
            return jsonify({'error': f'Node does not support {handler_name}'}), 400
        
        def generate():
            for img_data in method():
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + img_data + b'\r\n')
        
        return Response(
            stream_with_context(generate()),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )
    
    app.add_url_rule(
        f'/api/nodes/<node_id>/{route}',
        endpoint=endpoint_name,
        view_func=handler,
        methods=['GET']
    )


# Register all dynamic routes at startup (before app.run)
_register_dynamic_node_routes()

# Queue for debug messages (for SSE)
debug_message_queues = {}
debug_broadcast_thread = None
debug_broadcast_running = False
debug_broadcast_lock = threading.Lock()

def start_debug_broadcast():
    """Start a single background thread that polls nodes and broadcasts to all clients."""
    global debug_broadcast_thread, debug_broadcast_running
    
    with debug_broadcast_lock:
        if debug_broadcast_running:
            return
        
        debug_broadcast_running = True
        debug_broadcast_thread = threading.Thread(target=_debug_broadcast_worker, daemon=True)
        debug_broadcast_thread.start()

def _debug_broadcast_worker():
    """Background worker that polls nodes and broadcasts to all connected clients.
    Uses the SSE handler registry to dynamically discover what to broadcast."""
    last_throttle_update = {}  # handler_key -> last_update_time
    
    while debug_broadcast_running:
        try:
            # Only poll if there are connected clients
            if not debug_message_queues:
                time.sleep(0.1)
                continue
            
            current_time = time.time()
            messages_sent = False
            
            # Get errors from system error node
            all_errors = deployed_engine.get_system_errors()
            if all_errors:
                data = {'type': 'errors', 'data': all_errors}
                _broadcast_to_all_clients(data)
                deployed_engine.clear_system_errors()
                messages_sent = True
            
            # Poll all nodes that have registered SSE handlers
            for node_id, node in deployed_engine.nodes.items():
                if node.type not in _sse_handler_registry:
                    continue
                
                for handler_def in _sse_handler_registry[node.type]:
                    event_type = handler_def['type']
                    handler_name = handler_def['handler']
                    throttle = handler_def.get('throttle')
                    
                    # Check throttle
                    if throttle is not None:
                        handler_key = f"{node_id}_{event_type}"
                        last_update = last_throttle_update.get(handler_key, 0)
                        if current_time - last_update < throttle:
                            continue
                        last_throttle_update[handler_key] = current_time
                    
                    handler = getattr(node, handler_name, None)
                    if handler is None or not callable(handler):
                        continue
                    
                    try:
                        result = handler()
                        if result is None:
                            continue
                        
                        # Special handling for 'messages' type: wrap in data key
                        if event_type == 'messages':
                            data = {'type': 'messages', 'data': result}
                        else:
                            data = {
                                'type': event_type,
                                'nodeId': node_id,
                            }
                            # If result is a dict, merge it into data
                            # (handler returns keys like 'display', 'rate', etc.)
                            if isinstance(result, dict):
                                data.update(result)
                            else:
                                data['data'] = result
                        
                        _broadcast_to_all_clients(data)
                        messages_sent = True
                    except Exception as e:
                        print(f"SSE handler error ({node.type}.{handler_name}): {e}")
            
            # Adaptive sleep
            if messages_sent:
                time.sleep(0.01)
            else:
                time.sleep(0.05)
                
        except Exception as e:
            print(f"Debug broadcast error: {e}")
            time.sleep(0.1)

def _broadcast_to_all_clients(data):
    """Send data to all connected SSE clients."""
    dead_clients = []
    for client_id, q in list(debug_message_queues.items()):
        try:
            q.put_nowait(data)
        except queue.Full:
            # Client queue is full, skip
            pass
        except Exception:
            dead_clients.append(client_id)
    
    # Clean up dead clients
    for client_id in dead_clients:
        debug_message_queues.pop(client_id, None)

# Track if workflow has been loaded
workflow_loaded = False


def save_workflow_to_disk():
    """Save the current working workflow to disk with backup."""
    try:
        # Backup existing workflow if it exists
        if os.path.exists(WORKFLOW_FILE):
            try:
                # Create backup directory inside workflows folder
                backup_dir = os.path.join(WORKFLOWS_DIR, '_backups')
                os.makedirs(backup_dir, exist_ok=True)
                
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_file = os.path.join(backup_dir, f'workflow_{timestamp}.json')
                shutil.copy2(WORKFLOW_FILE, backup_file)
                print(f"Backed up workflow to {backup_file}")
            except (PermissionError, OSError) as e:
                print(f"Warning: Failed to create backup: {e}")
                # Continue preventing backup failure from stopping save
        
        # Save new workflow
        workflow_data = working_engine.export_workflow()
        with open(WORKFLOW_FILE, 'w') as f:
            json.dump(workflow_data, f, indent=2)
        print(f"Workflow saved to {WORKFLOW_FILE}")
        
    except PermissionError:
        print(f"ERROR: Permission denied when saving to {WORKFLOW_FILE}")
        print("Please run the following command in terminal to fix ownership:")
        print(f"  sudo chown -R $USER:$USER {WORKFLOWS_DIR}")
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
        import traceback
        print(f"Failed to load workflow: {e}")
        print(f"Error type: {type(e).__name__}")
        print(f"Full traceback:")
        traceback.print_exc()
        # Even on error, start the deployed engine to ensure system nodes exist
        try:
            deployed_engine.start()
        except:
            pass


@app.route('/')
def index():
    """Serve the main UI."""
    return send_from_directory(os.path.join(PKG_DIR, 'static'), 'index.html')


@app.route('/api/node-types', methods=['GET'])
def get_node_types():
    """Get all available node types (excluding system nodes like ErrorNode)."""
    global _node_types_cache
    if _node_types_cache is None:
        _build_node_types_cache()
    return jsonify(_node_types_cache)


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


@app.route('/api/workflow/deploy-changes', methods=['POST'])
def deploy_changes():
    """Incrementally deploy only changed nodes without stopping the entire workflow."""
    try:
        data = request.json
        modified_nodes = data.get('modifiedNodes', [])
        added_nodes = data.get('addedNodes', [])
        deleted_nodes = data.get('deletedNodes', [])
        added_connections = data.get('addedConnections', [])
        deleted_connections = data.get('deletedConnections', [])
        
        nodes_restarted = 0
        
        # 1. Delete removed connections first
        for conn in deleted_connections:
            try:
                deployed_engine.disconnect_nodes(
                    conn['source'], 
                    conn['target'], 
                    conn.get('sourceOutput', 0)
                )
                working_engine.disconnect_nodes(
                    conn['source'], 
                    conn['target'], 
                    conn.get('sourceOutput', 0)
                )
            except Exception as e:
                print(f"Error deleting connection: {e}")
        
        # 2. Delete removed nodes
        for node_id in deleted_nodes:
            try:
                # Stop the node first
                node = deployed_engine.get_node(node_id)
                if node:
                    node.on_stop()
                deployed_engine.delete_node(node_id)
                working_engine.delete_node(node_id)
                nodes_restarted += 1
            except Exception as e:
                print(f"Error deleting node {node_id}: {e}")
        
        # 3. Add new nodes
        for node_data in added_nodes:
            try:
                # Create in deployed engine
                node = deployed_engine.create_node(
                    node_type=node_data['type'],
                    node_id=node_data['id'],
                    name=node_data.get('name', ''),
                    config=node_data.get('config', {})
                )
                node.enabled = node_data.get('enabled', True)
                node.x = node_data.get('x', 0)
                node.y = node_data.get('y', 0)
                
                # Start the new node if engine is running
                if deployed_engine.running:
                    node.on_start()
                
                # Create in working engine
                w_node = working_engine.create_node(
                    node_type=node_data['type'],
                    node_id=node_data['id'],
                    name=node_data.get('name', ''),
                    config=node_data.get('config', {})
                )
                w_node.enabled = node_data.get('enabled', True)
                w_node.x = node_data.get('x', 0)
                w_node.y = node_data.get('y', 0)
                
                nodes_restarted += 1
            except Exception as e:
                print(f"Error adding node: {e}")
        
        # 4. Update modified nodes (stop, reconfigure, restart)
        for node_data in modified_nodes:
            node_id = node_data['id']
            try:
                deployed_node = deployed_engine.get_node(node_id)
                working_node = working_engine.get_node(node_id)
                
                if deployed_node:
                    # Stop the node
                    deployed_node.on_stop()
                    
                    # Update configuration
                    deployed_node.name = node_data.get('name', deployed_node.name)
                    deployed_node.configure(node_data.get('config', {}))
                    deployed_node.enabled = node_data.get('enabled', True)
                    deployed_node.x = node_data.get('x', 0)
                    deployed_node.y = node_data.get('y', 0)
                    
                    # Restart the node
                    if deployed_engine.running:
                        deployed_node.on_start()
                    
                    nodes_restarted += 1
                
                if working_node:
                    working_node.name = node_data.get('name', working_node.name)
                    working_node.configure(node_data.get('config', {}))
                    working_node.enabled = node_data.get('enabled', True)
                    working_node.x = node_data.get('x', 0)
                    working_node.y = node_data.get('y', 0)
                    
            except Exception as e:
                print(f"Error updating node {node_id}: {e}")
        
        # 5. Add new connections
        for conn in added_connections:
            try:
                deployed_engine.connect_nodes(
                    conn['source'],
                    conn['target'],
                    conn.get('sourceOutput', 0),
                    conn.get('targetInput', 0)
                )
                working_engine.connect_nodes(
                    conn['source'],
                    conn['target'],
                    conn.get('sourceOutput', 0),
                    conn.get('targetInput', 0)
                )
            except Exception as e:
                print(f"Error adding connection: {e}")
        
        # Save the updated workflow to disk
        save_workflow_to_disk()
        
        return jsonify({
            'success': True, 
            'nodesRestarted': nodes_restarted
        }), 200
        
    except Exception as e:
        print(f"Error in incremental deploy: {e}")
        return jsonify({'error': str(e)}), 400


@app.route('/api/workflow/restart', methods=['POST'])
def restart_workflow():
    """Restart the deployed workflow by re-importing and starting all nodes."""
    try:
        # Export current deployed workflow state
        workflow_data = deployed_engine.export_workflow()
        
        # Stop, re-import, and start - this fully reinitializes all nodes
        deployed_engine.stop()
        deployed_engine.import_workflow(workflow_data)
        deployed_engine.start()
        
        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"Error restarting workflow: {e}")
        return jsonify({'error': str(e)}), 400


@app.route('/api/workflow/stats', methods=['GET'])
def get_workflow_stats():
    """Get deployed workflow statistics."""
    return jsonify(deployed_engine.get_workflow_stats())


# ==============================================================================
# MQTT Service Management API
# ==============================================================================

@app.route('/api/services/mqtt', methods=['GET'])
def list_mqtt_services():
    """List all MQTT services."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        services = mqtt_manager.list_services()
        return jsonify({'success': True, 'services': services})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/services/mqtt', methods=['POST'])
def create_mqtt_service():
    """Create a new MQTT service."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        data = request.json
        
        # Validate required fields
        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Service name is required'}), 400
        if not data.get('broker'):
            return jsonify({'success': False, 'error': 'Broker address is required'}), 400
        
        service = mqtt_manager.create_service(data)
        return jsonify({
            'success': True,
            'service': {
                'id': service.id,
                'name': service.name,
                'broker': service.broker,
                'port': service.port
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/services/mqtt/<service_id>', methods=['GET'])
def get_mqtt_service(service_id):
    """Get a specific MQTT service by ID."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        service = mqtt_manager.get_service(service_id)
        if not service:
            return jsonify({'success': False, 'error': 'Service not found'}), 404
        
        return jsonify({
            'success': True,
            'service': service.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/services/mqtt/<service_id>', methods=['PUT'])
def update_mqtt_service(service_id):
    """Update an existing MQTT service."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        data = request.json
        
        service = mqtt_manager.update_service(service_id, data)
        if not service:
            return jsonify({'success': False, 'error': 'Service not found'}), 404
        
        return jsonify({
            'success': True,
            'service': service.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/services/mqtt/<service_id>', methods=['DELETE'])
def delete_mqtt_service(service_id):
    """Delete an MQTT service."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        
        if not mqtt_manager.delete_service(service_id):
            return jsonify({
                'success': False, 
                'error': 'Service not found or still in use'
            }), 400
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/services/mqtt/<service_id>/test', methods=['POST'])
def test_mqtt_service(service_id):
    """Test connection to an MQTT service."""
    try:
        from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager
        
        service = mqtt_manager.get_service(service_id)
        if not service:
            return jsonify({'success': False, 'error': 'Service not found'}), 404
        
        # Try to connect
        connected = service.connect()
        
        return jsonify({
            'success': True,
            'connected': connected,
            'status': 'connected' if connected else 'failed'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==============================================================================
# Model Upload API
# ==============================================================================

@app.route('/api/upload/model', methods=['POST'])
def upload_model():
    """Upload a model file for inference nodes."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        if not file.filename or file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        # Create models directory if it doesn't exist
        models_dir = os.path.join(os.path.dirname(__file__), 'models')
        os.makedirs(models_dir, exist_ok=True)
        
        # Save the file
        filename = file.filename
        model_path = os.path.join(models_dir, filename)
        file.save(model_path)
        
        return jsonify({
            'success': True,
            'model_path': model_path,
            'filename': filename
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/nodes/<node_id>/<action>', methods=['POST'])
def trigger_node_action(node_id, action):
    """Trigger a button action on a node in deployed workflow."""
    try:
        node = deployed_engine.get_node(node_id)
        if not node:
            return jsonify({'error': 'Node not found'}), 404
        
        # Check if the node has the action method
        if not hasattr(node, action):
            return jsonify({'error': f'Action {action} not found on node'}), 404
        
        # Call the action method
        method = getattr(node, action)
        if callable(method):
            method()
            return jsonify({'status': 'success', 'action': action})
        else:
            return jsonify({'error': f'{action} is not a callable method'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/debug/stream')
def debug_stream():
    """Server-Sent Events stream for debug messages."""
    def generate():
        # Create a queue for this client
        q = queue.Queue(maxsize=100)
        client_id = id(q)
        debug_message_queues[client_id] = q
        
        # Start broadcast thread if not running
        start_debug_broadcast()
        
        try:
            yield 'data: {"type": "connected"}\n\n'
            
            while True:
                try:
                    # Wait for data from broadcast thread
                    data = q.get(timeout=1.0)
                    yield f'data: {json.dumps(data)}\n\n'
                except queue.Empty:
                    # Send keepalive
                    yield 'data: {"type": "keepalive"}\n\n'
                    
        except GeneratorExit:
            # Client disconnected
            debug_message_queues.pop(client_id, None)
        except Exception as e:
            # Log error and close connection
            print(f"SSE Error: {e}")
            debug_message_queues.pop(client_id, None)
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


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
