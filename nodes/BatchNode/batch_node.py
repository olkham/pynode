"""
Batch Node - groups messages into batches.
"""

from typing import Any, Dict, List
from nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Collects incoming messages into batches and sends them together as an array.")
_info.add_header("Input")
_info.add_bullets(
    ("payload:", "Any message payload to be collected into a batch."),
)
_info.add_header("Output")
_info.add_bullets(
    ("payload:", "Array of payloads from the batched messages."),
    ("batch_size:", "Number of messages in the batch."),
)
_info.add_header("Properties")
_info.add_bullets(
    ("Batch Size:", "Number of messages to collect before sending."),
    ("Overlap:", "Number of messages to retain for the next batch."),
)


class BatchNode(BaseNode):
    """
    Batch Node - collects messages into batches and sends them together.
    """
    info = str(_info)
    display_name = 'Batch'
    icon = '📦'
    category = 'function'
    color = '#DDA0DD'
    border_color = '#BA55D3'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'batch_size': 10,
        'overlap': 0,
        'drop_messages': False
    }
    
    properties = [
        {
            'name': 'batch_size',
            'label': 'Batch Size',
            'type': 'number',
            'default': DEFAULT_CONFIG['batch_size']
        },
        {
            'name': 'overlap',
            'label': 'Overlap (messages)',
            'type': 'number',
            'default': DEFAULT_CONFIG['overlap'],
        }
    ]
    
    def __init__(self, node_id=None, name="batch"):
        super().__init__(node_id, name)
        self.buffer = []
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Collect messages into batches."""
        self.buffer.append(msg.copy())
        
        batch_size = self.get_config_int('batch_size', 10)
        
        if len(self.buffer) >= batch_size:
            # Send batch
            batch = self.buffer[:batch_size]
            out_msg = self.create_message(
                payload=[m.get('payload') for m in batch],
                topic=batch[0].get('topic', '') if batch else '',
                batch_size=len(batch)
            )
            self.send(out_msg)
            
            # Handle overlap
            overlap = self.get_config_int('overlap', 0)
            if overlap > 0 and overlap < batch_size:
                self.buffer = self.buffer[batch_size - overlap:]
            else:
                self.buffer = []
