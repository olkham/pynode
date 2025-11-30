"""
Base Node class for the Python Node-RED-like system.
All custom nodes should inherit from this class.
"""

import uuid
import queue
import threading
from typing import Dict, List, Any, Optional


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
    properties = [
        {
            'name': 'drop_messages',
            'label': 'Drop Messages When Busy',
            'type': 'select',
            'options': [
                {'value': 'false', 'label': 'No (Queue messages)'},
                {'value': 'true', 'label': 'Yes (Drop when busy)'}
            ],
            'default': 'false'
        }
    ]
    
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
        
        # Non-blocking message queue
        self._message_queue = queue.Queue(maxsize=1000)  # Limit queue size to prevent memory issues
        self._worker_thread = None
        self._stop_worker_flag = False
        
        # Initialize drop_while_busy flag from config (defaults to False)
        self.drop_while_busy = False
        
        # Error handling
        self._workflow_engine = None  # Will be set by workflow engine
        
    def set_workflow_engine(self, engine):
        """Set reference to the workflow engine for error reporting."""
        self._workflow_engine = engine
    
    def report_error(self, error_msg: str):
        """
        Report an error to all ErrorNodes in the workflow.
        
        Args:
            error_msg: The error message to report
        """
        if self._workflow_engine:
            self._workflow_engine.broadcast_error(self.id, self.name, error_msg)
        
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
        Send a message to connected nodes (non-blocking).
        Messages are queued and processed asynchronously.
        
        Args:
            msg: Message dictionary (must have 'payload' and 'topic')
            output_index: Which output port to send from (default 0)
        """
        if not self.enabled:
            return
            
        if output_index in self.outputs:
            connections = self.outputs[output_index]
            num_connections = len(connections)
            
            for i, (target_node, target_input) in enumerate(connections):
                if target_node.enabled:
                    # Only copy message if sending to multiple targets and not the last one
                    msg_to_send = msg.copy() if i < num_connections - 1 else msg
                    
                    # Check if target node prefers direct processing (no outputs = sink node)
                    if target_node.output_count == 0 and hasattr(target_node, 'on_input_direct'):
                        # Direct processing for sink nodes (no queuing overhead)
                        try:
                            target_node.on_input_direct(msg_to_send, target_input)
                        except Exception as e:
                            print(f"Error in direct processing for node {target_node.id}: {e}")
                    else:
                        # Queue message for target node (non-blocking)
                        try:
                            # Check if target wants to drop messages when busy
                            if target_node.drop_while_busy and not target_node._message_queue.empty():
                                # Drop message instead of queuing
                                continue
                            
                            target_node._message_queue.put_nowait((msg_to_send, target_input))
                        except queue.Full:
                            # Queue full - drop message or handle overflow
                            print(f"Warning: Message queue full for node {target_node.id}, dropping message")
    
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
    
    def _start_worker(self):
        """
        Start the worker thread to process queued messages.
        """
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_worker_flag = False
            self._worker_thread = threading.Thread(target=self._process_messages, daemon=True)
            self._worker_thread.start()
    
    def _process_messages(self):
        """
        Worker thread that processes messages from the queue.
        Uses adaptive timeout to balance responsiveness with CPU usage.
        """
        idle_count = 0
        while not self._stop_worker_flag:
            try:
                # Adaptive timeout: faster when active, slower when idle
                timeout = 0.01 if idle_count < 10 else 0.1
                msg, input_index = self._message_queue.get(timeout=timeout)
                idle_count = 0  # Reset on successful message
                
                # Process the message
                try:
                    self.on_input(msg, input_index)
                except Exception as e:
                    print(f"Error processing message in node {self.id}: {e}")
                finally:
                    self._message_queue.task_done()
                    
            except queue.Empty:
                # No message available, increase idle count
                idle_count += 1
                continue
            except Exception as e:
                print(f"Worker thread error in node {self.id}: {e}")
    
    def on_start(self):
        """
        Called when the node is started/deployed.
        Override to implement initialization logic.
        """
        # Start message processing worker
        self._start_worker()
    
    def on_stop(self):
        """
        Called when the node is stopped.
        Override to implement cleanup logic.
        """
        # Stop message processing worker
        self._stop_worker_flag = True
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
    
    def configure(self, config: Dict[str, Any]):
        """
        Configure the node with settings.
        
        Args:
            config: Configuration dictionary
        """
        self.config.update(config)
        # Update drop_while_busy flag from config
        self.drop_while_busy = self.config.get('drop_messages', 'false') == 'true'
    
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
