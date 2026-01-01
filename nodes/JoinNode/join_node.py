"""
Join Node - combines multiple messages into one.
"""

import time
from typing import Any, Dict, List
from nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Combines multiple messages into a single output message. Similar to Node-RED's join node.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Messages to be combined.")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Combined message with aggregated payloads.")
)
_info.add_header("Join Modes")
_info.add_bullets(
    ("Automatic:", "Send combined result after each message."),
    ("Count:", "Wait for N messages before combining."),
    ("Timeout:", "Combine messages after a time delay.")
)
_info.add_header("Combine Types")
_info.add_bullets(
    ("Array:", "payload becomes [msg1.payload, msg2.payload, ...]"),
    ("Object:", "Merge all message payloads into one object."),
    ("String:", "Concatenate all payloads as strings.")
)


class JoinNode(BaseNode):
    """
    Join Node - combines messages from multiple sources into a single output.
    Similar to Node-RED's join node.
    """
    display_name = 'Join'
    icon = '🔗'
    category = 'function'
    color = '#E9967A'
    border_color = '#CD853F'
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
                {'value': 'auto', 'label': 'Automatic (after each message)'},
                {'value': 'count', 'label': 'After a fixed number of messages'},
                {'value': 'time', 'label': 'After a timeout'}
            ]
        },
        {
            'name': 'count',
            'label': 'Message Count',
            'type': 'number',
            'default': 2
        },
        {
            'name': 'timeout',
            'label': 'Timeout (seconds)',
            'type': 'number',
            'default': 1.0
        },
        {
            'name': 'combine',
            'label': 'Combine Into',
            'type': 'select',
            'options': [
                {'value': 'array', 'label': 'Array (msg.payload = [msg1, msg2, ...])'},
                {'value': 'object', 'label': 'Object (merge all messages)'},
                {'value': 'string', 'label': 'String (concatenate)'}
            ]
        }
    ]
    
    def __init__(self, node_id=None, name="join"):
        super().__init__(node_id, name)
        self.configure({
            'mode': 'count',
            'count': 2,
            'timeout': 1.0,
            'combine': 'array',
            'drop_messages': False
        })
        self.message_buffer = []
        self.first_message_time = None
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Buffer messages and combine them based on configuration."""
        self.message_buffer.append(msg.copy())
        
        if self.first_message_time is None:
            self.first_message_time = time.time()
        
        mode = self.config.get('mode', 'count')
        should_send = False
        
        if mode == 'auto':
            should_send = True
        elif mode == 'count':
            count = self.get_config_int('count', 2)
            if len(self.message_buffer) >= count:
                should_send = True
        elif mode == 'time':
            timeout = self.get_config_float('timeout', 1.0)
            if time.time() - self.first_message_time >= timeout:
                should_send = True
        
        if should_send:
            self._send_combined()
    
    def _send_combined(self):
        """Combine buffered messages and send."""
        if not self.message_buffer:
            return
        
        combine_type = self.config.get('combine', 'array')
        
        try:
            if combine_type == 'array':
                # Combine into array of payloads
                combined_payload = [msg.get('payload') for msg in self.message_buffer]
            elif combine_type == 'object':
                # Merge all messages into one object
                combined_payload = {}
                for msg in self.message_buffer:
                    payload = msg.get('payload')
                    if isinstance(payload, dict):
                        combined_payload.update(payload)
                    else:
                        # Use index as key if not a dict
                        combined_payload[f'msg_{len(combined_payload)}'] = payload
            else:  # string
                # Concatenate payloads as strings
                combined_payload = ' '.join(str(msg.get('payload', '')) for msg in self.message_buffer)
            
            output_msg = self.create_message(
                payload=combined_payload,
                topic=self.message_buffer[0].get('topic', ''),
                message_count=len(self.message_buffer)
            )
            
            self.send(output_msg)
        except Exception as e:
            self.report_error(f"Error combining messages: {e}")
        finally:
            # Clear buffer
            self.message_buffer.clear()
            self.first_message_time = None
