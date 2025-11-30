"""
Filter Node - filters messages based on conditions.
"""

from typing import Any, Dict
from nodes.base_node import BaseNode


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
            'drop_messages': 'false'
        })
        self.last_value = None
        self.message_count = 0
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Filter messages based on configured mode."""
        mode = self.config.get('mode', 'dedupe')
        payload = msg.get('payload')
        
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
            count = int(self.config.get('count', 1))
            self.message_count += 1
            if self.message_count > count:
                should_send = True
        elif mode == 'keep_first':
            # Keep only first N messages
            count = int(self.config.get('count', 1))
            self.message_count += 1
            if self.message_count <= count:
                should_send = True
        
        if should_send:
            self.send(msg)
