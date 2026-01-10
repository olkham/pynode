"""
Counter Node - counts messages and displays the count with a reset button.
Demonstrates the use of UI components (button + rate-display).
"""

from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Counts incoming messages and outputs the running total. Includes a reset button to restart the count.")
_info.add_header("Input")
_info.add_bullets(
    ("msg:", "Any message triggers the counter increment."),
)
_info.add_header("Output")
_info.add_bullets(
    ("payload.count:", "Current count value."),
    ("payload.original_payload:", "The original payload from the input message."),
    ("payload.display:", "Formatted count for display."),
)
_info.add_header("Properties")
_info.add_bullets(
    ("Initial Value:", "Starting count value."),
    ("Increment By:", "Amount to add per message."),
)
_info.add_header("UI")
_info.add_text("Click the reset button on the node to reset the counter to initial value.")


class CounterNode(BaseNode):
    """
    Counter node - counts incoming messages and displays the total.
    Can be reset via button click.
    """
    info = str(_info)
    display_name = 'Counter'
    icon = '🔢'
    category = 'node probes'
    color = '#E2D96E'
    border_color = '#B8AF4A'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    # Counter display UI component with reset button
    ui_component = 'counter-display'
    ui_component_config = {
        'format': '{value}',
        'action': 'reset_counter',
        'tooltip': 'Reset Count'
    }
    
    DEFAULT_CONFIG = {
        'initial_value': '0',
        'increment': '1',
        'retain_payload': 'false',
        MessageKeys.DROP_MESSAGES: 'false'
    }
    
    properties = [
        {
            'name': MessageKeys.DROP_MESSAGES,
            'label': 'Drop Messages When Busy',
            'type': 'checkbox',
            'default': False
        },
        {
            'name': 'initial_value',
            'label': 'Initial Value',
            'type': 'text',
            'default': DEFAULT_CONFIG['initial_value'],
            'help': 'Starting count value'
        },
        {
            'name': 'increment',
            'label': 'Increment By',
            'type': 'text',
            'default': DEFAULT_CONFIG['increment'],
            'help': 'Amount to increment per message'
        },
        {
            'name': 'retain_payload',
            'label': 'Retain Original Payload',
            'type': 'select',
            'options': [
                {'value': 'false', 'label': 'No - Replace payload with count info'},
                {'value': 'true', 'label': 'Yes - Merge count info into payload'}
            ],
            'default': DEFAULT_CONFIG['retain_payload'],
            'help': 'Whether to keep original payload data or replace it'
        }
    ]
    
    def __init__(self, node_id=None, name="counter"):
        super().__init__(node_id, name)
        self.count = 0
        self._reset_to_initial()
    
    def _reset_to_initial(self):
        """Reset counter to initial value from config."""
        self.count = self.get_config_int('initial_value', 0)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Increment counter and pass through with count information.
        """
        # Get increment value
        increment = self.get_config_int('increment', 1)
        
        # Increment counter
        self.count += increment
        
        # Build count info
        count_info = {
            'count': self.count,
            'display': self.get_count_display()
        }
        
        # Check if we should retain original payload
        if self.get_config_bool('retain_payload', False):
            original_payload = msg.get(MessageKeys.PAYLOAD, {})
            if isinstance(original_payload, dict):
                new_payload = original_payload.copy()
                new_payload.update(count_info)
            else:
                new_payload = {
                    'original_data': original_payload,
                    **count_info
                }
        else:
            new_payload = count_info
        
        msg[MessageKeys.PAYLOAD] = new_payload
        msg[MessageKeys.TOPIC] = msg.get(MessageKeys.TOPIC, 'counter')
        
        self.send(msg)
    
    def get_count(self) -> int:
        """Get the current count value."""
        return self.count
    
    def get_count_display(self) -> str:
        """Get formatted count string for display."""
        return str(self.count)
    
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
                'display': self.get_count_display()
            },
            topic='counter/reset'
        )
        self.send(msg)
