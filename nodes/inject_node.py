"""
Inject node - generates messages with a payload.
Similar to Node-RED's inject node.
"""

import time
import threading
from base_node import BaseNode


class InjectNode(BaseNode):
    """
    Inject node - generates messages with a payload.
    Similar to Node-RED's inject node.
    """
    display_name = 'Inject'
    icon = '⏱'
    category = 'input'
    color = '#C0DEED'
    border_color = '#87A9C1'
    text_color = '#000000'
    input_count = 0
    output_count = 1
    
    properties = [
        {
            'name': 'payloadType',
            'label': 'Payload Type',
            'type': 'select',
            'options': [
                {'value': 'date', 'label': 'Timestamp'},
                {'value': 'string', 'label': 'String'},
                {'value': 'num', 'label': 'Number'},
                {'value': 'bool', 'label': 'Boolean'},
                {'value': 'json', 'label': 'JSON'}
            ]
        },
        {
            'name': 'payload',
            'label': 'Payload',
            'type': 'text'
        },
        {
            'name': 'topic',
            'label': 'Topic',
            'type': 'text'
        },
        {
            'name': 'once',
            'label': 'Inject once after',
            'type': 'text',
            'help': 'Delay in seconds (leave empty to disable)'
        },
        {
            'name': 'repeat',
            'label': 'Repeat interval',
            'type': 'text',
            'help': 'Interval in seconds (leave empty to disable)'
        },
        {
            'name': 'inject',
            'label': 'Inject',
            'type': 'button',
            'action': 'inject'
        }
    ]
    
    def __init__(self, node_id=None, name="inject"):
        super().__init__(node_id, name)
        self.configure({
            'payload': 'timestamp',
            'payloadType': 'date',
            'topic': '',
            'repeat': '',
            'once': ''
        })
        self._timer_thread = None
        self._stop_timer = False
        self._once_timer = None
    
    def inject(self):
        """
        Manually trigger an injection.
        """
        payload_type = self.config.get('payloadType', 'date')
        
        if payload_type == 'date':
            payload = time.time()
        elif payload_type == 'string':
            payload = str(self.config.get('payload', ''))
        elif payload_type == 'num':
            payload = float(self.config.get('payload', 0))
        elif payload_type == 'bool':
            payload = bool(self.config.get('payload', False))
        elif payload_type == 'json':
            payload = self.config.get('payload', {})
        else:
            payload = self.config.get('payload')
        
        msg = self.create_message(
            payload=payload,
            topic=self.config.get('topic', '')
        )
        self.send(msg)
    
    def on_start(self):
        """
        Start timers if configured.
        """
        # Handle "inject once after delay"
        once_delay = self.config.get('once', '')
        if once_delay and str(once_delay).strip():
            try:
                delay_seconds = float(once_delay)
                self._once_timer = threading.Timer(delay_seconds, self.inject)
                self._once_timer.daemon = True
                self._once_timer.start()
            except (ValueError, TypeError):
                pass
        
        # Handle "repeat interval"
        repeat_interval = self.config.get('repeat', '')
        if repeat_interval and str(repeat_interval).strip():
            try:
                interval_seconds = float(repeat_interval)
                self._stop_timer = False
                self._timer_thread = threading.Thread(
                    target=self._repeat_timer,
                    args=(interval_seconds,),
                    daemon=True
                )
                self._timer_thread.start()
            except (ValueError, TypeError):
                pass
    
    def _repeat_timer(self, interval):
        """
        Background timer for repeated injections.
        """
        while not self._stop_timer:
            time.sleep(interval)
            if not self._stop_timer:
                self.inject()
    
    def on_stop(self):
        """
        Stop all timers when workflow stops.
        """
        self._stop_timer = True
        if self._once_timer and self._once_timer.is_alive():
            self._once_timer.cancel()
        if self._timer_thread and self._timer_thread.is_alive():
            # Thread will stop on next iteration
            pass
    
    def on_close(self):
        """
        Clean up when node is deleted.
        """
        self.on_stop()
