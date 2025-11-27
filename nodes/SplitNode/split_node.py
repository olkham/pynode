"""
Split Node - splits arrays or strings into separate messages.
"""

from typing import Any, Dict
from base_node import BaseNode


class SplitNode(BaseNode):
    """
    Split Node - splits arrays or strings into separate messages.
    Similar to Node-RED's split node.
    """
    display_name = 'Split'
    icon = '✂️'
    category = 'function'
    color = '#F0E68C'
    border_color = '#DAA520'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'split_type',
            'label': 'Split Type',
            'type': 'select',
            'options': [
                {'value': 'auto', 'label': 'Auto-detect'},
                {'value': 'array', 'label': 'Array'},
                {'value': 'string', 'label': 'String'},
                {'value': 'object', 'label': 'Object (key-value pairs)'}
            ]
        },
        {
            'name': 'delimiter',
            'label': 'String Delimiter',
            'type': 'text',
            'default': ','
        }
    ]
    
    def __init__(self, node_id=None, name="split"):
        super().__init__(node_id, name)
        self.configure({
            'split_type': 'auto',
            'delimiter': ',',
            'drop_messages': 'false'
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Split incoming message into multiple messages."""
        payload = msg.get('payload')
        split_type = self.config.get('split_type', 'auto')
        
        items = []
        
        # Auto-detect or explicit type
        if split_type == 'auto':
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict):
                items = list(payload.items())
            elif isinstance(payload, str):
                delimiter = self.config.get('delimiter', ',')
                items = payload.split(delimiter)
            else:
                self.report_error(f"Cannot split payload of type {type(payload)}")
                return
        elif split_type == 'array':
            if isinstance(payload, list):
                items = payload
            else:
                self.report_error("Payload is not an array")
                return
        elif split_type == 'string':
            if isinstance(payload, str):
                delimiter = self.config.get('delimiter', ',')
                items = payload.split(delimiter)
            else:
                items = str(payload).split(self.config.get('delimiter', ','))
        elif split_type == 'object':
            if isinstance(payload, dict):
                items = list(payload.items())
            else:
                self.report_error("Payload is not an object")
                return
        
        # Send each item as a separate message
        for i, item in enumerate(items):
            # For object splits, item is a tuple (key, value)
            if isinstance(item, tuple) and len(item) == 2:
                item_payload = {'key': item[0], 'value': item[1]}
            else:
                item_payload = item
            
            out_msg = self.create_message(
                payload=item_payload,
                topic=msg.get('topic', ''),
                parts={
                    'index': i,
                    'count': len(items),
                    'id': msg.get('_msgid')
                }
            )
            
            self.send(out_msg)
