"""
Gate node - allows messages to pass through or blocks them.
Can be toggled on/off directly from the UI without redeployment.
"""

from typing import Any, Dict
from base_node import BaseNode


class GateNode(BaseNode):
    """
    Gate node - allows or blocks messages based on enabled state.
    Can be toggled in real-time from the UI.
    """
    display_name = 'Gate'
    icon = '🚪'
    category = 'logic'
    color = '#FFE5B4'
    border_color = '#FFD700'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    properties = []  # No properties panel needed
    
    def __init__(self, node_id=None, name="gate"):
        super().__init__(node_id, name)
        self.enabled = True  # Gate is open (enabled) by default
        self.configure({})
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Pass message through if gate is enabled, otherwise discard it.
        """
        if self.enabled:
            self.send(msg)
        # If gate is disabled, message is silently discarded
