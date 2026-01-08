"""
Range Node - scales/maps values from one range to another.
"""

from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Maps numeric values from one range to another using linear interpolation. Useful for scaling sensor data, normalizing values, or converting between units.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with numeric payload to scale")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Message with scaled payload value")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Input Min/Max:", "The expected range of input values"),
    ("Output Min/Max:", "The desired range of output values"),
    ("Clamp:", "If enabled, output is constrained to the output range")
)
_info.add_header("Example")
_info.add_text("Input range 0-100 to output range 0-1: A value of 50 becomes 0.5")


class RangeNode(BaseNode):
    """
    Range Node - maps numeric values from one range to another.
    Similar to Node-RED's range node.
    """
    info = str(_info)
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
            'drop_messages': False
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Map payload value from input range to output range."""
        try:
            payload = msg.get(MessageKeys.PAYLOAD)
            value = float(payload)
            
            min_in = self.get_config_float('min_in', 0)
            max_in = self.get_config_float('max_in', 100)
            min_out = self.get_config_float('min_out', 0)
            max_out = self.get_config_float('max_out', 1)
            clamp = self.get_config_bool('clamp', True)
            
            # Map value
            if max_in == min_in:
                mapped = min_out
            else:
                mapped = ((value - min_in) / (max_in - min_in)) * (max_out - min_out) + min_out
            
            # Clamp if enabled
            if clamp:
                mapped = max(min(mapped, max(min_out, max_out)), min(min_out, max_out))
            
            # Preserve original message properties (like frame_count)
            # Note: send() handles deep copying, so we modify msg directly
            msg[MessageKeys.PAYLOAD] = mapped
            self.send(msg)
            
        except (ValueError, TypeError) as e:
            self.report_error(f"Invalid numeric value: {e}")
