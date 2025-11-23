"""
Base Node class for the Python Node-RED-like system.
All custom nodes should inherit from this class.
"""

import uuid
from typing import Dict, List, Any, Callable, Optional


class BaseNode:
    """
    Base class for all nodes in the workflow system.
    Messages follow Node-RED structure with 'payload' and 'topic' fields.
    """
    
    # Visual properties (can be overridden by subclasses)
    display_name = 'Base Node'  # Display name (without 'Node' suffix)
    icon = '◆'  # Icon character or emoji
    category = 'custom'
    color = '#2d2d30'
    border_color = '#555'
    text_color = '#d4d4d4'
    input_count = 1  # Number of input ports (0 for input-only nodes)
    output_count = 1  # Number of output ports (0 for output-only nodes)
    
    # Property schema for the properties panel
    # Format: [{'name': 'propName', 'label': 'Display Label', 'type': 'text|textarea|select|button', 'options': [...], 'action': 'methodName'}]
    properties = []
    
    def __init__(self, node_id: Optional[str] = None, name: str = ""):
        """
        Initialize a base node.
        
        Args:
            node_id: Unique identifier for the node. Auto-generated if not provided.
            name: Human-readable name for the node.
        """
        self.id = node_id or str(uuid.uuid4())
        self.name = name or self.__class__.__name__
        self.type = self.__class__.__name__
        
        # Connections: output_index -> [(target_node, target_input_index), ...]
        self.outputs: Dict[int, List[tuple]] = {}
        
        # Configuration for the node
        self.config: Dict[str, Any] = {}
        
        # Node state
        self.enabled = True
        
    def connect(self, target_node: 'BaseNode', output_index: int = 0, target_input_index: int = 0):
        """
        Connect this node's output to another node's input.
        
        Args:
            target_node: The node to connect to
            output_index: Which output port to use (default 0)
            target_input_index: Which input port on target (default 0)
        """
        if output_index not in self.outputs:
            self.outputs[output_index] = []
        
        self.outputs[output_index].append((target_node, target_input_index))
        
    def disconnect(self, target_node: 'BaseNode', output_index: int = 0):
        """
        Disconnect this node from a target node.
        
        Args:
            target_node: The node to disconnect from
            output_index: Which output port to disconnect
        """
        if output_index in self.outputs:
            self.outputs[output_index] = [
                (node, idx) for node, idx in self.outputs[output_index]
                if node.id != target_node.id
            ]
    
    def create_message(self, payload: Any, topic: str = "", **kwargs) -> Dict[str, Any]:
        """
        Create a message in Node-RED format.
        
        Args:
            payload: The message payload (any type)
            topic: Optional topic string
            **kwargs: Additional message properties
            
        Returns:
            Message dictionary with at least payload and topic
        """
        msg = {
            'payload': payload,
            'topic': topic,
            '_msgid': str(uuid.uuid4())
        }
        msg.update(kwargs)
        return msg
    
    def send(self, msg: Dict[str, Any], output_index: int = 0):
        """
        Send a message to connected nodes.
        
        Args:
            msg: Message dictionary (must have 'payload' and 'topic')
            output_index: Which output port to send from (default 0)
        """
        if not self.enabled:
            return
            
        if output_index in self.outputs:
            for target_node, target_input in self.outputs[output_index]:
                if target_node.enabled:
                    # Pass message to target node
                    target_node.on_input(msg, target_input)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Called when this node receives a message.
        Override this method in subclasses to implement node logic.
        
        Args:
            msg: Message dictionary with 'payload', 'topic', etc.
            input_index: Which input port received the message
        """
        # Default behavior: pass through
        self.send(msg)
    
    def on_start(self):
        """
        Called when the node is started/deployed.
        Override to implement initialization logic.
        """
        pass
    
    def on_stop(self):
        """
        Called when the node is stopped.
        Override to implement cleanup logic.
        """
        pass
    
    def configure(self, config: Dict[str, Any]):
        """
        Configure the node with settings.
        
        Args:
            config: Configuration dictionary
        """
        self.config.update(config)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize node to dictionary for API/storage.
        
        Returns:
            Dictionary representation of the node
        """
        return {
            'id': self.id,
            'type': self.type,
            'name': self.name,
            'config': self.config,
            'enabled': self.enabled,
            'outputs': {
                str(idx): [(node.id, target_idx) for node, target_idx in connections]
                for idx, connections in self.outputs.items()
            }
        }
    
    def __repr__(self):
        return f"<{self.type}(id={self.id}, name={self.name})>"
