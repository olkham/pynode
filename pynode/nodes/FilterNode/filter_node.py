"""
Filter Node - filters messages based on conditions.
"""

from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Filters messages based on various conditions. Only passes messages that meet the specified criteria.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Any message to be filtered.")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Messages that pass the filter.")
)
_info.add_header("Filter Modes")
_info.add_bullets(
    ("Block:", "Block unless payload value changes."),
    ("Dedupe:", "Block duplicate payloads (same as Block)."),
    ("Drop First:", "Drop the first N messages, pass the rest."),
    ("Keep First:", "Keep only the first N messages, drop the rest.")
)


class FilterNode(BaseNode):
    """
    Filter Node - only passes messages that meet specified conditions.
    """
    display_name = 'Filter'
    icon = '🔍'
    category = 'function'
    color = '#FFB6C1'
    border_color = '#FF69B4'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    info = str(_info)
    
    properties = [
        {
            'name': 'mode',
            'label': 'Mode',
            'type': 'select',
            'options': [
                {'value': 'block', 'label': 'Block unless value changes'},
                {'value': 'dedupe', 'label': 'Deduplicate (block duplicates)'},
                {'value': 'drop_first', 'label': 'Drop first N messages'},
                {'value': 'keep_first', 'label': 'Keep only first N messages'}
            ]
        },
        {
            'name': 'count',
            'label': 'Count',
            'type': 'number',
            'default': 1
        }
    ]
    
    def __init__(self, node_id=None, name="filter"):
        super().__init__(node_id, name)
        self.configure({
            'mode': 'dedupe',
            'count': 1,
            'drop_messages': False
        })
        self.last_value = None
        self.message_count = 0
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Filter messages based on configured mode."""
        mode = self.config.get('mode', 'dedupe')
        payload = msg.get(MessageKeys.PAYLOAD)
        
        should_send = False
        
        if mode == 'block':
            # Block unless value changes
            if payload != self.last_value:
                should_send = True
                self.last_value = payload
        elif mode == 'dedupe':
            # Deduplicate
            if payload != self.last_value:
                should_send = True
                self.last_value = payload
        elif mode == 'drop_first':
            # Drop first N messages
            count = self.get_config_int('count', 1)
            self.message_count += 1
            if self.message_count > count:
                should_send = True
        elif mode == 'keep_first':
            # Keep only first N messages
            count = self.get_config_int('count', 1)
            self.message_count += 1
            if self.message_count <= count:
                should_send = True
        
        if should_send:
            self.send(msg)
