"""
Delay node - delays message delivery.
Similar to Node-RED's delay node.
"""

import time
import threading
from collections import deque
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Delays or rate-limits message delivery. Similar to Node-RED's delay node.")
_info.add_header("Input")
_info.add_bullets(
    ("msg:", "Any message to be delayed or rate-limited."),
)
_info.add_header("Output")
_info.add_bullets(
    ("msg:", "The original message after the configured delay."),
)
_info.add_header("Modes")
_info.add_bullets(
    ("Delay each message:", "Hold each message for a fixed time before sending."),
    ("Delay by message count:", "Release messages after N more messages arrive."),
    ("Rate limit:", "Limit throughput to N messages per time period."),
)
_info.add_header("Properties")
_info.add_bullets(
    ("Delay (seconds):", "Time to delay each message."),
    ("Delay (messages):", "Number of messages to buffer before releasing."),
    ("Rate/Time:", "Messages per time period for rate limiting."),
    ("Intermediate Messages:", "Drop or queue messages during rate limiting."),
)


class DelayNode(BaseNode):
    """
    Delay node - delays message delivery (non-blocking).
    Similar to Node-RED's delay node.
    """
    info = str(_info)
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
        'timeout': 0,
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
            'showIf': {'mode': ['delay']}
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
        # Timestamp (time.monotonic clock) of the next slot at which a message
        # is allowed to pass in rate-limit mode. None until the first message.
        self._next_allowed: 'float | None' = None
        self.queued_messages = []
        self.processing_queue = False
        self.queue_lock = threading.Lock()
        # Buffer for count-based delay
        self._message_buffer: deque = deque()

    def on_start(self):
        """Initialize on start."""
        super().on_start()
        self._message_buffer.clear()
        with self.queue_lock:
            self._next_allowed = None
            self.queued_messages.clear()
            self.processing_queue = False
    
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
    
    def _interval(self) -> float:
        """Seconds between allowed messages: rate_time / rate."""
        rate = self.get_config_int('rate', 1)
        rate_time = self.get_config_float('rate_time', 1)
        # Guard against a zero/negative rate configuration.
        return rate_time / rate if rate > 0 else rate_time

    @staticmethod
    def _slack(interval: float) -> float:
        """Jitter tolerance: a message arriving up to this early still passes.

        Scheduling jitter can make a message that is nominally due at slot S
        arrive a few ms early; without slack that message is dropped and the
        NEXT arrival (a full source-period later) becomes the one that passes,
        which halves the effective throughput. Cap at half an interval so slack
        can never let two messages through in one slot.
        """
        return min(0.05, interval / 2.0)

    def _advance_slot(self, now: float, interval: float):
        """Advance the next-allowed slot after a message passes.

        Advance from the SCHEDULE (``self._next_allowed``) rather than from
        ``now`` so steady arrivals don't accumulate drift. Clamp with ``now``
        so that after a long idle gap the schedule jumps forward to the present
        instead of leaving a stale slot in the past (which would let a burst
        through). Either way at most one message passes per interval.
        """
        self._next_allowed = max(self._next_allowed or now, now) + interval

    def _rate_limit(self, msg: Dict[str, Any]):
        """
        Rate limit messages - only send at specified rate.

        Uses a scheduled-slot (token-bucket-style) limiter keyed off a
        monotonic ``_next_allowed`` timestamp so that steady input at the
        configured rate produces steady output, independent of small timing
        jitter.
        """
        rate_drop = self.config.get('rate_drop', 'drop')
        interval = self._interval()
        slack = self._slack(interval)

        with self.queue_lock:
            now = time.monotonic()
            if self._next_allowed is None:
                # First message ever: allow it now and start the schedule here.
                self._next_allowed = now

            if not self.queued_messages and now >= self._next_allowed - slack:
                # We're at (or acceptably close to) an open slot: pass it.
                self.send(msg)
                self._advance_slot(now, interval)
            elif rate_drop == 'queue':
                # Buffer for later delivery and make sure the drainer is running.
                self.queued_messages.append(msg)
                if not self.processing_queue:
                    self.processing_queue = True
                    delay = max(0.0, self._next_allowed - now)
                    timer = threading.Timer(delay, self._process_queued)
                    timer.daemon = True
                    timer.start()
            # else: drop (do nothing)

    def _process_queued(self):
        """Process next queued message if available (queue mode drainer)."""
        with self.queue_lock:
            if not self.queued_messages:
                self.processing_queue = False
                return

            interval = self._interval()
            msg = self.queued_messages.pop(0)
            now = time.monotonic()
            if self._next_allowed is None:
                self._next_allowed = now
            self.send(msg)
            self._advance_slot(now, interval)

            # Schedule next message if queue not empty
            if self.queued_messages:
                delay = max(0.0, self._next_allowed - now)
                timer = threading.Timer(delay, self._process_queued)
                timer.daemon = True
                timer.start()
            else:
                self.processing_queue = False
