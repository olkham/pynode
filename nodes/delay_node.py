"""
Delay node - delays message delivery.
Similar to Node-RED's delay node.
"""

import time
from typing import Any, Dict
from base_node import BaseNode


class DelayNode(BaseNode):
    """
    Delay node - delays message delivery.
    Similar to Node-RED's delay node.
    """
    display_name = 'Delay'
    icon = '⧗'
    category = 'function'
    color = '#E6E0F8'
    border_color = '#9F93C6'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'timeout',
            'label': 'Delay (seconds)',
            'type': 'number'
        }
    ]
    
    def __init__(self, node_id=None, name="delay"):
        super().__init__(node_id, name)
        self.configure({
            'timeout': 1,  # seconds
            'timeoutUnits': 'seconds',
            'rate': 1,
            'rateUnits': 'second'
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Delay the message (simple implementation - synchronous).
        For production, use threading or async.
        """
        timeout = self.config.get('timeout', 1)
        time.sleep(timeout)
        self.send(msg)
