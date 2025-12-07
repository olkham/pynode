"""
Auto Sync Node - joins messages from multiple inputs and outputs them together.
Simply buffers the latest message from each input and outputs all when a new message arrives.
"""

from typing import Any, Dict, Optional
from nodes.base_node import BaseNode


class AutoSyncNode(BaseNode):
    """
    Auto Sync node - joins messages from multiple inputs.
    Buffers the latest message from each input and outputs them together
    along with the delta between sync property values.
    """
    display_name = 'Auto Sync'
    icon = '⚡'
    category = 'logic'
    color = '#FFB347'
    border_color = '#CC8F39'
    text_color = '#000000'
    input_count = 2  # Default, can be changed via properties
    output_count = 1
    
    DEFAULT_CONFIG = {
        'input_count': 2,
        'sync_property': 'frame_count'
    }
    
    properties = [
        {
            'name': 'input_count',
            'label': 'Number of Inputs',
            'type': 'number',
            'default': DEFAULT_CONFIG['input_count'],
            'min': 2,
            'max': 10,
            'help': 'Number of input ports to join'
        },
        {
            'name': 'sync_property',
            'label': 'Sync Property Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['sync_property'],
            'help': 'Property path to compare for delta (e.g., "frame_count", "timestamp")'
        }
    ]
    
    def __init__(self, node_id=None, name="auto sync"):
        super().__init__(node_id, name)
        self._buffers: Dict[int, Optional[Dict[str, Any]]] = {}
        
        self.configure(self.DEFAULT_CONFIG)
    
    def configure(self, config: Dict[str, Any]):
        """Configure node and update input count."""
        super().configure(config)
        
        new_input_count = self.get_config_int('input_count', 2)
        if new_input_count != self.input_count:
            self.input_count = new_input_count
            self._buffers = {i: None for i in range(self.input_count)}
    
    def on_start(self):
        """Initialize buffers on start."""
        super().on_start()
        self._buffers = {i: None for i in range(self.input_count)}
    
    def _get_nested_value(self, obj: Dict, path: str) -> Any:
        """Get a nested value from a dictionary using dot notation."""
        parts = path.split('.')
        current = obj
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current
    
    def _get_sync_value(self, msg: Dict[str, Any]) -> Optional[float]:
        """Extract the sync property value from a message."""
        sync_property = self.config.get('sync_property', 'frame_count')
        
        # Try direct message property first
        value = msg.get(sync_property)
        
        # If not found, try nested path
        if value is None:
            value = self._get_nested_value(msg, sync_property)
        
        # If still not found, try in payload
        if value is None and 'payload' in msg:
            value = self._get_nested_value(msg['payload'], sync_property)
        
        # Convert to float if possible
        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                return None
        
        return None
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Process incoming messages."""
        if input_index >= self.input_count:
            self.report_error(f"Received message on invalid input {input_index}")
            return
        
        # Buffer the message
        self._buffers[input_index] = msg
        
        # Check if all inputs have messages
        messages = []
        sync_values = []
        
        for i in range(self.input_count):
            buffered = self._buffers.get(i)
            if buffered is None:
                return  # Not all inputs have messages yet
            messages.append(buffered)
            sync_values.append(self._get_sync_value(buffered))
        
        # All inputs have messages - compute delta and output
        valid_values = [v for v in sync_values if v is not None]
        if valid_values:
            delta = max(valid_values) - min(valid_values)
        else:
            delta = None
        
        # Build output
        out_msg = {
            'payload': {
                'messages': [m.get('payload') for m in messages],
                'sync_values': sync_values,
                'delta': delta
            }
        }
        
        # Copy other properties from first message
        for key in messages[0]:
            if key not in ('payload', '_msgid'):
                out_msg[key] = messages[0][key]
        
        self.send(out_msg)
