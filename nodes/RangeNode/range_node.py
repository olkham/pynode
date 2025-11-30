"""
Range Node - scales/maps values from one range to another.
"""

from typing import Any, Dict
from nodes.base_node import BaseNode


class RangeNode(BaseNode):
    """
    Range Node - maps numeric values from one range to another.
    Similar to Node-RED's range node.
    """
    display_name = 'Range'
    icon = '📊'
    category = 'function'
    color = '#87CEEB'
    border_color = '#4682B4'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'min_in',
            'label': 'Input Min',
            'type': 'number',
            'default': 0
        },
        {
            'name': 'max_in',
            'label': 'Input Max',
            'type': 'number',
            'default': 100
        },
        {
            'name': 'min_out',
            'label': 'Output Min',
            'type': 'number',
            'default': 0
        },
        {
            'name': 'max_out',
            'label': 'Output Max',
            'type': 'number',
            'default': 1
        },
        {
            'name': 'clamp',
            'label': 'Clamp to Output Range',
            'type': 'checkbox',
            'default': True
        }
    ]
    
    def __init__(self, node_id=None, name="range"):
        super().__init__(node_id, name)
        self.configure({
            'min_in': 0,
            'max_in': 100,
            'min_out': 0,
            'max_out': 1,
            'clamp': True,
            'drop_messages': 'false'
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Map payload value from input range to output range."""
        try:
            payload = msg.get('payload')
            value = float(payload)
            
            min_in = float(self.config.get('min_in', 0))
            max_in = float(self.config.get('max_in', 100))
            min_out = float(self.config.get('min_out', 0))
            max_out = float(self.config.get('max_out', 1))
            clamp = self.config.get('clamp', True)
            
            # Map value
            if max_in == min_in:
                mapped = min_out
            else:
                mapped = ((value - min_in) / (max_in - min_in)) * (max_out - min_out) + min_out
            
            # Clamp if enabled
            if clamp:
                mapped = max(min(mapped, max(min_out, max_out)), min(min_out, max_out))
            
            out_msg = self.create_message(
                payload=mapped,
                topic=msg.get('topic', '')
            )
            self.send(out_msg)
            
        except (ValueError, TypeError) as e:
            self.report_error(f"Invalid numeric value: {e}")
