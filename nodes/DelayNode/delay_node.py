"""
Delay node - delays message delivery.
Similar to Node-RED's delay node.
"""

import time
import threading
from collections import deque
from typing import Any, Dict
from nodes.base_node import BaseNode


class DelayNode(BaseNode):
    """
    Delay node - delays message delivery (non-blocking).
    Similar to Node-RED's delay node.
    """
    display_name = 'Delay'
    icon = '⧗'
    category = 'function'
    color = '#E6E0F8'
    border_color = '#9F93C6'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'mode': 'delay',
        'timeout': 1,
        'delay_count': 1,
        'rate': 1,
        'rate_time': 1,
        'rate_drop': 'drop',
        'drop_messages': False
    }
    
    properties = [
        {
            'name': 'mode',
            'label': 'Mode',
            'type': 'select',
            'options': [
                {'value': 'delay', 'label': 'Delay each message'},
                {'value': 'delay_count', 'label': 'Delay by message count'},
                {'value': 'rate', 'label': 'Rate limit'}
            ]
        },
        {
            'name': 'timeout',
            'label': 'Delay (seconds)',
            'type': 'number',
            'default': DEFAULT_CONFIG['timeout'],
            'help': 'Delay time in seconds (for time-based delay)',
            'showIf': {'mode': ['delay', 'rate']}
        },
        {
            'name': 'delay_count',
            'label': 'Delay (messages)',
            'type': 'number',
            'default': DEFAULT_CONFIG['delay_count'],
            'min': 1,
            'help': 'Number of messages to delay by (for count-based delay)',
            'showIf': {'mode': 'delay_count'}
        },
        {
            'name': 'rate',
            'label': 'Rate Limit (count)',
            'type': 'number',
            'default': DEFAULT_CONFIG['rate'],
            'showIf': {'mode': 'rate'}
        },
        {
            'name': 'rate_time',
            'label': 'Per Time (seconds)',
            'type': 'number',
            'default': DEFAULT_CONFIG['rate_time'],
            'showIf': {'mode': 'rate'}
        },
        {
            'name': 'rate_drop',
            'label': 'Intermediate Messages',
            'type': 'select',
            'options': [
                {'value': 'drop', 'label': 'Drop'},
                {'value': 'queue', 'label': 'Queue'}
            ],
            'showIf': {'mode': 'rate'}
        }
    ]
    
    def __init__(self, node_id=None, name="delay"):
        super().__init__(node_id, name)
        self.last_send_time = 0
        self.queued_messages = []
        self.processing_queue = False
        self.queue_lock = threading.Lock()
        # Buffer for count-based delay
        self._message_buffer: deque = deque()
    
    def on_start(self):
        """Initialize on start."""
        super().on_start()
        self._message_buffer.clear()
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Handle message based on mode: delay each message, delay by count, or rate limit.
        """
        mode = self.config.get('mode', 'delay')
        
        if mode == 'delay':
            # Delay each message by time
            timeout = self.get_config_float('timeout', 1)
            timer = threading.Timer(timeout, self.send, args=(msg,))
            timer.daemon = True
            timer.start()
        elif mode == 'delay_count':
            # Delay by message count
            self._delay_by_count(msg)
        else:
            # Rate limiting mode
            self._rate_limit(msg)
    
    def _delay_by_count(self, msg: Dict[str, Any]):
        """
        Delay messages by a number of messages.
        Each message is released after N more messages have arrived.
        """
        delay_count = self.get_config_int('delay_count', 1)
        
        # Add message to buffer
        self._message_buffer.append(msg)
        
        # If buffer has more messages than delay count, release the oldest
        while len(self._message_buffer) > delay_count:
            oldest_msg = self._message_buffer.popleft()
            self.send(oldest_msg)
    
    def _rate_limit(self, msg: Dict[str, Any]):
        """
        Rate limit messages - only send at specified rate.
        """
        rate = self.get_config_int('rate', 1)
        rate_time = self.get_config_float('rate_time', 1)
        rate_drop = self.config.get('rate_drop', 'drop')
        
        # Calculate interval: time / count
        interval = rate_time / rate
        
        with self.queue_lock:
            current_time = time.time()
            time_since_last = current_time - self.last_send_time
            
            if time_since_last >= interval and not self.queued_messages:
                # Enough time has passed and no queue, send immediately
                self.send(msg)
                self.last_send_time = current_time
            else:
                # Too soon or queue exists, handle based on drop/queue setting
                if rate_drop == 'queue':
                    self.queued_messages.append(msg)
                    # Start processing queue if not already running
                    if not self.processing_queue:
                        self.processing_queue = True
                        delay = max(0, interval - time_since_last)
                        timer = threading.Timer(delay, self._process_queued)
                        timer.daemon = True
                        timer.start()
                # else: drop (do nothing)
    
    def _process_queued(self):
        """Process next queued message if available."""
        with self.queue_lock:
            if not self.queued_messages:
                self.processing_queue = False
                return
            
            msg = self.queued_messages.pop(0)
            current_time = time.time()
            self.send(msg)
            self.last_send_time = current_time
            
            # Schedule next message if queue not empty
            if self.queued_messages:
                rate = self.get_config_int('rate', 1)
                rate_time = self.get_config_float('rate_time', 1)
                interval = rate_time / rate
                
                timer = threading.Timer(interval, self._process_queued)
                timer.daemon = True
                timer.start()
            else:
                self.processing_queue = False
