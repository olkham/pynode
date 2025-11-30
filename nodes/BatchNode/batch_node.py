"""
Batch Node - groups messages into batches.
"""

from typing import Any, Dict, List
from nodes.base_node import BaseNode


class BatchNode(BaseNode):
    """
    Batch Node - collects messages into batches and sends them together.
    """
    display_name = 'Batch'
    icon = '📦'
    category = 'function'
    color = '#DDA0DD'
    border_color = '#BA55D3'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'batch_size',
            'label': 'Batch Size',
            'type': 'number',
            'default': 10
        },
        {
            'name': 'overlap',
            'label': 'Overlap (messages)',
            'type': 'number',
            'default': 0
        }
    ]
    
    def __init__(self, node_id=None, name="batch"):
        super().__init__(node_id, name)
        self.configure({
            'batch_size': 10,
            'overlap': 0,
            'drop_messages': 'false'
        })
        self.buffer = []
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Collect messages into batches."""
        self.buffer.append(msg.copy())
        
        batch_size = int(self.config.get('batch_size', 10))
        
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
            overlap = int(self.config.get('overlap', 0))
            if overlap > 0 and overlap < batch_size:
                self.buffer = self.buffer[batch_size - overlap:]
            else:
                self.buffer = []
