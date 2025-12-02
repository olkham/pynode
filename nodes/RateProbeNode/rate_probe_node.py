"""
Rate Probe Node - monitors message throughput rate.
Passes messages through while tracking and displaying the rate.
"""

import time
from typing import Any, Dict
from collections import deque
from nodes.base_node import BaseNode


class RateProbeNode(BaseNode):
    """
    Rate Probe node - monitors and displays message rate.
    Passes all messages through unchanged while tracking throughput.
    """
    display_name = 'Rate Probe'
    icon = '📊'
    category = 'function'
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
    
    properties = [
        {
            'name': 'window_size',
            'label': 'Window Size (seconds)',
            'type': 'number',
            'default': 1.0,
            'help': 'Time window for calculating rate'
        }
    ]
    
    def __init__(self, node_id=None, name="rate probe"):
        super().__init__(node_id, name)
        self.configure({
            'window_size': 1.0
        })
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
        window_size = float(self.config.get('window_size', 1.0))
        
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
        
        # Send rate as payload
        rate_msg = self.create_message(
            payload={
                'rate': self._current_rate,
                'display': self.get_rate_display(),
                'window_size': window_size,
                'message_count': len(self._timestamps)
            },
            topic=msg.get('topic', 'rate')
        )
        self.send(rate_msg)
    
    def get_rate(self) -> float:
        """Get the current message rate."""
        current_time = time.time()
        window_size = float(self.config.get('window_size', 1.0))
        
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
