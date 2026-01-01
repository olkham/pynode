"""
Rate Probe Node - monitors message throughput rate.
Passes messages through while tracking and displaying the rate.
"""

import time
from typing import Any, Dict
from collections import deque
from nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Monitors message throughput rate by counting messages within a time window. Displays the rate on the node and outputs rate information.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Any message to count")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Message with rate statistics in payload")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Window Size:", "Time window in seconds for calculating the rate (default: 1 second)")
)
_info.add_header("Output Message")
_info.add_code('msg.payload.rate').text(" - Messages per second as a number").end()
_info.add_code('msg.payload.display').text(" - Human-readable rate string (e.g., '30/s', '2.5k/s')").end()
_info.add_code('msg.payload.message_count').text(" - Number of messages in the current window").end()


class RateProbeNode(BaseNode):
    """
    Rate Probe node - monitors and displays message rate.
    Passes all messages through unchanged while tracking throughput.
    """
    info = str(_info)
    display_name = 'Rate Probe'
    icon = '📊'
    category = 'measurement'
    color = '#E2D96E'
    border_color = '#B8AF4A'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    ui_component = 'rate-display'
    ui_component_config = {
        'format': '{value}/s',
        'precision': 1
    }

    DEFAULT_CONFIG = {
        'window_size': 1.0  # in seconds
    }

    properties = [
        {
            'name': 'window_size',
            'label': 'Window Size (seconds)',
            'type': 'number',
            'default': DEFAULT_CONFIG['window_size'],
            'help': 'Time window for calculating rate'
        }
    ]
    
    def __init__(self, node_id=None, name="rate probe"):
        super().__init__(node_id, name)
        # Store timestamps of recent messages
        self._timestamps = deque()
        self._current_rate = 0.0
        self._last_update = time.time()
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Pass through the message and update rate calculation.
        Sends rate information as the payload.
        """
        current_time = time.time()
        window_size = self.get_config_float('window_size', 1.0)
        
        # Add current timestamp
        self._timestamps.append(current_time)
        
        # Remove timestamps outside the window
        cutoff = current_time - window_size
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        
        # Calculate rate (messages per second)
        if window_size > 0:
            self._current_rate = len(self._timestamps) / window_size
        else:
            self._current_rate = 0.0
        
        self._last_update = current_time
        
        # Preserve original message properties (like frame_count) and add rate info
        # Note: send() handles deep copying, so we modify msg directly
        msg['payload'] = {
            'rate': self._current_rate,
            'display': self.get_rate_display(),
            'window_size': window_size,
            'message_count': len(self._timestamps)
        }
        msg['topic'] = msg.get('topic', 'rate')
        self.send(msg)
    
    def get_rate(self) -> float:
        """Get the current message rate."""
        current_time = time.time()
        window_size = self.get_config_float('window_size', 1.0)
        
        # Clean up old timestamps
        cutoff = current_time - window_size
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        
        # Recalculate rate
        if window_size > 0:
            self._current_rate = len(self._timestamps) / window_size
        
        return self._current_rate
    
    def get_rate_display(self) -> str:
        """Get formatted rate string for display."""
        rate = self.get_rate()
        if rate >= 1000:
            # Format as k/s, hide .0 precision
            formatted = f"{rate/1000:.1f}".rstrip('0').rstrip('.')
            return f"{formatted}k/s"
        elif rate >= 1:
            # Format as /s, hide .0 precision
            formatted = f"{rate:.1f}".rstrip('0').rstrip('.')
            return f"{formatted}/s"
        elif rate > 0:
            # Below 1/s, show seconds per message
            interval = 1 / rate
            if interval >= 60:
                # Show in minutes
                minutes = interval / 60
                formatted = f"{minutes:.1f}".rstrip('0').rstrip('.')
                return f"{formatted}m/msg"
            else:
                # Show in seconds
                formatted = f"{interval:.1f}".rstrip('0').rstrip('.')
                return f"{formatted}s/msg"
        else:
            return "0/s"
    
    def on_stop(self):
        """Clear timestamps when stopped."""
        self._timestamps.clear()
        self._current_rate = 0.0
        super().on_stop()
