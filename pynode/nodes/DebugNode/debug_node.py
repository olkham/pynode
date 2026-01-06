"""
Debug node - prints messages to console.
Similar to Node-RED's debug node.
"""

import time
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Displays message content for debugging purposes. Similar to Node-RED's debug node.")
_info.add_header("Input")
_info.add_bullets(
    ("msg:", "Any message to inspect. Large values are automatically truncated."),
)
_info.add_header("Output")
_info.add_text("This node has no outputs. Messages are displayed in the debug panel.")
_info.add_header("Properties")
_info.add_bullets(
    ("Output:", "Show msg.payload only or complete message."),
)
_info.add_header("UI")
_info.add_text("Toggle the node on/off using the button. Last 10 messages are stored.")


class DebugNode(BaseNode):
    """
    Debug node - prints messages to console.
    Similar to Node-RED's debug node.
    """
    info = str(_info)
    display_name = 'Debug'
    icon = '🐛'
    category = 'common'
    color = '#87A980'
    border_color = '#5F7858'
    text_color = '#000000'
    input_count = 1
    output_count = 0
    ui_component = 'toggle'
    ui_component_config = {
        'action': 'toggle_debug',
        'label': 'Enable'
    }
    
    DEFAULT_CONFIG = {
        'console': True,
        'complete': 'payload',
        'drop_messages': False
    }
    
    properties = [
        {
            'name': 'drop_messages',
            'label': 'Drop Messages When Busy',
            'type': 'checkbox',
            'default': False
        },
        {
            'name': 'complete',
            'label': 'Output',
            'type': 'select',
            'options': [
                {'value': 'payload', 'label': 'msg.payload'},
                {'value': 'msg', 'label': 'Complete msg'}
            ],
            'default': DEFAULT_CONFIG['complete']
        }
    ]
    
    def __init__(self, node_id=None, name="debug"):
        super().__init__(node_id, name)
        self.messages = []  # Store messages for API access
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Print/store the message for debugging.
        """
        # Skip if debug node is disabled
        if not self.enabled:
            return
        
        complete = self.config.get('complete', 'payload')
        
        if complete == 'msg':
            output = msg
            display_key = 'Complete msg'
        elif complete == 'payload':
            output = msg.get('payload')
            display_key = 'msg.payload'
        else:
            # Try to get nested property (only top-level for now)
            output = msg.get(complete, msg.get('payload'))
            display_key = f"msg.{complete}"


        # Recursively truncate large values in dicts/lists, but not the whole message
        def truncate_values(val, maxlen=300):
            if isinstance(val, (bytes, bytearray)):
                return f"<binary data, {len(val)} bytes>"
            elif isinstance(val, np.ndarray):
                return f"<numpy array, shape={val.shape}, dtype={val.dtype}>"
            elif isinstance(val, dict):
                return {k: truncate_values(v, maxlen) for k, v in val.items()}
            elif isinstance(val, list):
                return [truncate_values(v, maxlen) for v in val]
            else:
                s = str(val)
                if len(s) > maxlen:
                    return s[:maxlen] + f"... [truncated, {len(s)} chars]"
                return val

        display_output = truncate_values(output)

        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        debug_entry = {
            'timestamp': timestamp,
            'node': self.name,
            'node_id': self.id,
            'display_key': display_key,
            'output': display_output
        }
        
        self.messages.append(debug_entry)
        
        # Keep only last 10 messages
        if len(self.messages) > 10:
            self.messages = self.messages[-10:]
        
        # if self.config.get('console', True):
            # print(f"[{timestamp}] [{self.name}] {output}")
        
        # Pass through (optional)
        # self.send(msg)
    
    def set_enabled(self, enabled: bool):
        """Set the enabled state of the debug node."""
        self.enabled = enabled
    
    def get_enabled(self) -> bool:
        """Get the enabled state of the debug node."""
        return self.enabled
