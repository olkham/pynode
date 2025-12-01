"""
Inject node - generates messages with configurable properties.
Similar to Node-RED's inject node.
"""

import os
import json
import time
import threading
from nodes.base_node import BaseNode


class InjectNode(BaseNode):
    """
    Inject node - generates messages with configurable properties.
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
            'name': 'props',
            'label': 'Message Properties',
            'type': 'injectProps'
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
            'props': [
                {'property': 'payload', 'valueType': 'date', 'value': ''}
            ],
            'topic': '',
            'repeat': '',
            'once': ''
        })
        self._timer_thread = None
        self._stop_timer = False
        self._once_timer = None
    
    def _get_property_value(self, prop):
        """Convert a property definition to its actual value."""
        value_type = prop.get('valueType', 'str')
        raw_value = prop.get('value', '')
        
        if value_type == 'date':
            return time.time()
        elif value_type == 'str':
            return str(raw_value)
        elif value_type == 'num':
            try:
                return float(raw_value)
            except (ValueError, TypeError):
                return 0
        elif value_type == 'bool':
            return raw_value in ('true', True, 'True', '1', 1)
        elif value_type == 'json':
            try:
                return json.loads(raw_value) if raw_value else {}
            except (json.JSONDecodeError, TypeError):
                return {}
        elif value_type == 'env':
            return os.environ.get(str(raw_value), '')
        else:
            return raw_value
    
    def _set_nested_property(self, obj, path, value):
        """Set a nested property in an object using dot notation.
        
        e.g., _set_nested_property(msg, 'payload.data.value', 123)
        sets msg['payload']['data']['value'] = 123
        
        If a path segment already exists but is not a dict, it will be
        replaced with a dict to allow nested properties.
        """
        parts = path.split('.')
        current = obj
        
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        
        current[parts[-1]] = value
    
    def inject(self):
        """
        Manually trigger an injection.
        """
        msg = {}
        
        # Set topic if configured
        topic = self.config.get('topic', '')
        if topic:
            msg['topic'] = topic
        
        # Process all configured properties
        props = self.config.get('props', [])
        for prop in props:
            property_path = prop.get('property', 'payload')
            value = self._get_property_value(prop)
            self._set_nested_property(msg, property_path, value)
        
        # Send using create_message to add _msgid
        msg = self.create_message(**msg)
        self.send(msg)
    
    def on_start(self):
        """
        Start timers if configured.
        """
        # Start the base node worker thread
        super().on_start()
        
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
        Uses absolute timing to prevent drift.
        """
        next_time = time.time() + interval
        
        while not self._stop_timer:
            current_time = time.time()
            sleep_time = next_time - current_time
            
            if sleep_time > 0:
                time.sleep(sleep_time)
            
            if not self._stop_timer:
                self.inject()
                # Schedule next injection at fixed interval from the scheduled time
                next_time += interval
                
                # If we're running behind, catch up by skipping to the next valid time
                if next_time < time.time():
                    next_time = time.time() + interval
    
    def on_stop(self):
        """
        Stop all timers when workflow stops.
        """
        # Stop base node worker thread
        super().on_stop()
        
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
