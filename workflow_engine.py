"""
Workflow Engine for managing nodes and executing workflows.
"""

import threading
from typing import Dict, List, Any, Type, Optional
from base_node import BaseNode


class WorkflowEngine:
    """
    Manages a collection of nodes and their connections.
    Handles workflow execution and lifecycle.
    """
    
    def __init__(self):
        self.nodes: Dict[str, BaseNode] = {}
        self.node_types: Dict[str, Type[BaseNode]] = {}
        self.running = False
        self._lock = threading.RLock()  # Use RLock (reentrant lock) to allow nested locking
    
    def register_node_type(self, node_class: Type[BaseNode]):
        """
        Register a node type that can be instantiated.
        
        Args:
            node_class: A class that inherits from BaseNode
        """
        self.node_types[node_class.__name__] = node_class
    
    def create_node(self, node_type: str, node_id: Optional[str] = None, 
                   name: str = "", config: Optional[Dict[str, Any]] = None) -> BaseNode:
        """
        Create a new node instance and add it to the workflow.
        
        Args:
            node_type: The type of node to create (must be registered)
            node_id: Optional unique ID for the node
            name: Optional name for the node
            config: Optional configuration dictionary
            
        Returns:
            The created node instance
        """
        if node_type not in self.node_types:
            raise ValueError(f"Unknown node type: {node_type}")
        
        with self._lock:
            node_class = self.node_types[node_type]
            node = node_class(node_id=node_id, name=name)
            
            if config:
                node.configure(config)
            
            self.nodes[node.id] = node
            return node
    
    def get_node(self, node_id: str) -> Optional[BaseNode]:
        """
        Get a node by its ID.
        
        Args:
            node_id: The unique identifier of the node
            
        Returns:
            The node instance or None if not found
        """
        return self.nodes.get(node_id)
    
    def delete_node(self, node_id: str):
        """
        Remove a node from the workflow.
        
        Args:
            node_id: The unique identifier of the node to remove
        """
        with self._lock:
            if node_id in self.nodes:
                node = self.nodes[node_id]
                
                # Disconnect all outputs
                node.outputs.clear()
                
                # Disconnect all inputs (remove references from other nodes)
                for other_node in self.nodes.values():
                    for output_idx in list(other_node.outputs.keys()):
                        other_node.disconnect(node, output_idx)
                
                # Remove the node
                del self.nodes[node_id]
    
    def connect_nodes(self, source_id: str, target_id: str, 
                     output_index: int = 0, input_index: int = 0):
        """
        Connect two nodes together.
        
        Args:
            source_id: ID of the source node
            target_id: ID of the target node
            output_index: Output port index on source node
            input_index: Input port index on target node
        """
        source = self.get_node(source_id)
        target = self.get_node(target_id)
        
        if not source or not target:
            raise ValueError("Source or target node not found")
        
        with self._lock:
            source.connect(target, output_index, input_index)
    
    def disconnect_nodes(self, source_id: str, target_id: str, output_index: int = 0):
        """
        Disconnect two nodes.
        
        Args:
            source_id: ID of the source node
            target_id: ID of the target node
            output_index: Output port index on source node
        """
        source = self.get_node(source_id)
        target = self.get_node(target_id)
        
        if not source or not target:
            raise ValueError("Source or target node not found")
        
        with self._lock:
            source.disconnect(target, output_index)
    
    def start(self):
        """
        Start the workflow - calls on_start() for all nodes.
        """
        with self._lock:
            if self.running:
                return
            
            self.running = True
            
            for node in self.nodes.values():
                try:
                    node.on_start()
                except Exception as e:
                    print(f"Error starting node {node.id}: {e}")
    
    def stop(self):
        """
        Stop the workflow - calls on_stop() for all nodes.
        """
        with self._lock:
            if not self.running:
                return
            
            self.running = False
            
            for node in self.nodes.values():
                try:
                    node.on_stop()
                except Exception as e:
                    print(f"Error stopping node {node.id}: {e}")
    
    def trigger_inject_node(self, node_id: str):
        """
        Manually trigger an inject node.
        
        Args:
            node_id: ID of the inject node to trigger
        """
        node = self.get_node(node_id)
        if node and hasattr(node, 'inject'):
            node.inject()
        else:
            raise ValueError("Node not found or not an inject node")
    
    def get_debug_messages(self, node_id: str) -> List[Dict[str, Any]]:
        """
        Get debug messages from a debug node.
        
        Args:
            node_id: ID of the debug node
            
        Returns:
            List of debug messages
        """
        node = self.get_node(node_id)
        if node and hasattr(node, 'messages'):
            return node.messages
        return []
    
    def clear_debug_messages(self, node_id: str):
        """
        Clear debug messages from a debug node.
        
        Args:
            node_id: ID of the debug node
        """
        node = self.get_node(node_id)
        if node and hasattr(node, 'messages'):
            node.messages.clear()
    
    def export_workflow(self) -> Dict[str, Any]:
        """
        Export the entire workflow to a dictionary.
        
        Returns:
            Dictionary representation of the workflow
        """
        nodes_data = []
        connections_data = []
        
        for node in self.nodes.values():
            nodes_data.append({
                'id': node.id,
                'type': node.type,
                'name': node.name,
                'config': node.config,
                'enabled': node.enabled,
                'x': getattr(node, 'x', 0),
                'y': getattr(node, 'y', 0)
            })
            
            for output_idx, targets in node.outputs.items():
                for target_node, input_idx in targets:
                    connections_data.append({
                        'source': node.id,
                        'target': target_node.id,
                        'sourceOutput': output_idx,
                        'targetInput': input_idx
                    })
        
        return {
            'nodes': nodes_data,
            'connections': connections_data
        }
    
    def import_workflow(self, workflow_data: Dict[str, Any]):
        """
        Import a workflow from a dictionary.
        
        Args:
            workflow_data: Dictionary with 'nodes' and 'connections'
        """
        with self._lock:
            # Clear existing workflow
            self.nodes.clear()
            
            # Create nodes
            for node_data in workflow_data.get('nodes', []):
                node = self.create_node(
                    node_type=node_data['type'],
                    node_id=node_data['id'],
                    name=node_data.get('name', ''),
                    config=node_data.get('config', {})
                )
                node.enabled = node_data.get('enabled', True)
                # Store position if provided
                node.x = node_data.get('x', 0)
                node.y = node_data.get('y', 0)
            
            # Create connections
            for conn_data in workflow_data.get('connections', []):
                self.connect_nodes(
                    source_id=conn_data['source'],
                    target_id=conn_data['target'],
                    output_index=conn_data.get('sourceOutput', 0),
                    input_index=conn_data.get('targetInput', 0)
                )
    
    def get_workflow_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the current workflow.
        
        Returns:
            Dictionary with workflow statistics
        """
        node_types_count = {}
        total_connections = 0
        
        for node in self.nodes.values():
            node_type = node.type
            node_types_count[node_type] = node_types_count.get(node_type, 0) + 1
            
            for connections in node.outputs.values():
                total_connections += len(connections)
        
        return {
            'total_nodes': len(self.nodes),
            'total_connections': total_connections,
            'node_types': node_types_count,
            'running': self.running
        }
    
    def __repr__(self):
        return f"<WorkflowEngine(nodes={len(self.nodes)}, running={self.running})>"
