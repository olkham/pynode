"""
Split Node - splits arrays or strings into separate messages.
"""

from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Splits arrays, strings, or objects into separate messages. Each element becomes an individual message with parts metadata for reassembly.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with array, string, or object payload")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Multiple messages, one per element")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Split Type:", "Auto-detect, Array, String, or Object (key-value pairs)"),
    ("Delimiter:", "Character to split strings on (default: comma)")
)
_info.add_header("Output Message")
_info.add_code('msg.payload').text(" - Individual element from the split").end()
_info.add_code('msg.parts.index').text(" - Position in the original sequence").end()
_info.add_code('msg.parts.count').text(" - Total number of parts").end()
_info.add_code('msg.parts.id').text(" - ID to group related parts").end()


class SplitNode(BaseNode):
    """
    Split Node - splits arrays or strings into separate messages.
    Similar to Node-RED's split node.
    """
    info = str(_info)
    display_name = 'Split'
    icon = '✂️'
    category = 'function'
    color = '#F0E68C'
    border_color = '#DAA520'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'split_type': 'auto',
        'delimiter': ',',
        'drop_messages': False,
        'split_path': 'payload'
    }
    
    properties = [
        {
            'name': 'split_path',
            'label': 'Message Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['split_path']
        },
        {
            'name': 'split_type',
            'label': 'Split Type',
            'type': 'select',
            'options': [
                {'value': 'auto', 'label': 'Auto-detect'},
                {'value': 'array', 'label': 'Array'},
                {'value': 'string', 'label': 'String'},
                {'value': 'object', 'label': 'Object (key-value pairs)'}
            ],
            'default': DEFAULT_CONFIG['split_type']
        },
        {
            'name': 'delimiter',
            'label': 'String Delimiter',
            'type': 'text',
            'default': DEFAULT_CONFIG['delimiter'],
            'showIf': {'split_type': 'string'},
        }
    ]
    
    def __init__(self, node_id=None, name="split"):
        super().__init__(node_id, name)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Split incoming message into multiple messages."""
        split_path = self.config.get('split_path', 'payload')
        payload = self._get_nested_value(msg, split_path)
        
        if payload is None:
            self.report_error(f"No value found at path: {split_path}")
            return
        
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
        total_count = len(items)
        original_msgid = msg.get('_msgid')
        
        for i, item in enumerate(items):
            # Create a fresh copy of the message for each item
            out_msg = msg.copy()
            
            # For object splits, item is a tuple (key, value)
            if isinstance(item, tuple) and len(item) == 2:
                item_payload = {'key': item[0], 'value': item[1]}
            # For slice objects with embedded payload (from SliceImageNode)
            elif isinstance(item, dict) and 'payload' in item:
                item_payload = item['payload']
                # Copy other keys to message level (slice metadata)
                for key, value in item.items():
                    if key != 'payload':
                        out_msg[key] = value
            else:
                item_payload = item
            
            out_msg['payload'] = item_payload
            out_msg['parts'] = {
                'index': i,
                'count': total_count,
                'id': original_msgid
            }
            
            self.send(out_msg)
