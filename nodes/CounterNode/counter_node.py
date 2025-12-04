"""
Counter Node - counts messages and displays the count with a reset button.
Demonstrates the use of UI components (button + rate-display).
"""

from typing import Any, Dict
from nodes.base_node import BaseNode


class CounterNode(BaseNode):
    """
    Counter node - counts incoming messages and displays the total.
    Can be reset via button click.
    """
    display_name = 'Counter'
    icon = '🔢'
    category = 'measurement'
    color = '#B4D7FF'
    border_color = '#7BA7D7'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    # Button UI component for resetting
    ui_component = 'button'
    ui_component_config = {
        'icon': '↻',
        'action': 'reset_counter',
        'tooltip': 'Reset Count'
    }
    
    properties = [
        {
            'name': 'initial_value',
            'label': 'Initial Value',
            'type': 'text',
            'default': '0',
            'help': 'Starting count value'
        },
        {
            'name': 'increment',
            'label': 'Increment By',
            'type': 'text',
            'default': '1',
            'help': 'Amount to increment per message'
        }
    ]
    
    def __init__(self, node_id=None, name="counter"):
        super().__init__(node_id, name)
        self.configure({
            'initial_value': '0',
            'increment': '1'
        })
        self.count = 0
        self._reset_to_initial()
    
    def _reset_to_initial(self):
        """Reset counter to initial value from config."""
        try:
            self.count = int(self.config.get('initial_value', 0))
        except (ValueError, TypeError):
            self.count = 0
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Increment counter and pass through with count information.
        """
        # Get increment value
        try:
            increment = int(self.config.get('increment', 1))
        except (ValueError, TypeError):
            increment = 1
        
        # Increment counter
        self.count += increment
        
        # Preserve original message properties (like frame_count) and update payload
        # Note: send() handles deep copying, so we modify msg directly
        msg['payload'] = {
            'count': self.count,
            'original_payload': msg.get('payload'),
            'display': f'{self.count}'
        }
        msg['topic'] = msg.get('topic', 'counter')
        
        self.send(msg)
    
    def reset_counter(self):
        """
        Action triggered by the reset button.
        Resets counter to initial value and sends notification.
        """
        self._reset_to_initial()
        
        # Send reset notification
        msg = self.create_message(
            payload={
                'count': self.count,
                'action': 'reset',
                'display': f'{self.count}'
            },
            topic='counter/reset'
        )
        self.send(msg)
