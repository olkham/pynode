"""
Queue Length Probe Node - monitors message queue length.
Passes messages through while tracking and displaying the queue length.
"""

from typing import Any, Dict, Optional
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Monitors message queue length by displaying the _queue_length value from incoming messages. Displays the queue length on the node and outputs queue length information.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Any message to monitor (should contain _queue_length)")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", f"Original message with queue length statistics in {MessageKeys.PAYLOAD}")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("None:", "No configuration options")
)
_info.add_header("Output Message")
_info.add_code(f'{MessageKeys.MSG}.{MessageKeys.PAYLOAD}.queue_length').text(" - Current queue length as a number").end()
_info.add_code(f'{MessageKeys.MSG}.{MessageKeys.PAYLOAD}.display').text(" - Human-readable queue length string (e.g., '5 queued', '0 queued')").end()
_info.add_code(f'{MessageKeys.MSG}.{MessageKeys.PAYLOAD}.source_node').text(" - ID of the node where the queue length was measured").end()


class QueueLengthProbeNode(BaseNode):
    """
    Queue Length Probe node - monitors and displays message queue length.
    Passes all messages through unchanged while displaying queue length.
    """
    info = str(_info)
    display_name = 'Queue Length Probe'
    icon = '📊'
    category = 'node probes'
    color = '#E2D96E'
    border_color = '#B8AF4A'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    ui_component = 'queue-length-display'
    ui_component_config = {
        'format': '{value} queued',
        'precision': 0
    }

    DEFAULT_CONFIG = {
        MessageKeys.DROP_MESSAGES: 'false'
    }

    properties = [
        {
            'name': MessageKeys.DROP_MESSAGES,
            'label': 'Drop Messages When Busy',
            'type': 'checkbox',
            'default': False
        }
    ]
    
    def __init__(self, node_id=None, name="queue length probe"):
        super().__init__(node_id, name)
        self._current_queue_length = 0
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Pass through the message and extract queue length for display.
        Sends queue length information as the payload.
        """
        # Extract queue length from the message
        queue_length = msg.get(MessageKeys.QUEUE_LENGTH, 0)
        self._current_queue_length = queue_length
        
        # Replace payload with queue length statistics (like RateProbeNode)
        msg[MessageKeys.PAYLOAD] = {
            'queue_length': queue_length,
            'display': self.get_queue_length_display(queue_length),
            'source_node': msg.get('source_node_id', 'unknown')
        }
        msg[MessageKeys.TOPIC] = msg.get(MessageKeys.TOPIC, 'queue_length')
        
        # Send the message through
        self.send(msg)
    
    def get_queue_length(self) -> int:
        """Get the current queue length."""
        return self._current_queue_length
    
    def get_queue_length_display(self, queue_length: Optional[int] = None) -> str:
        """Get formatted queue length string for display."""
        if queue_length is None:
            queue_length = self._current_queue_length
            
        if queue_length == 0:
            return "No items queued"
        elif queue_length == 1:
            return "1 item queued"
        else:
            return f"{queue_length} items queued"
    
    def on_stop(self):
        """Reset queue length when stopped."""
        self._current_queue_length = 0
        super().on_stop()