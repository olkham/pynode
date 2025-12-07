"""
Function node - executes custom Python code on messages.
Similar to Node-RED's function node.
"""

import time
import copy
from typing import Any, Dict
from nodes.base_node import BaseNode


class FunctionNode(BaseNode):
    """
    Function node - executes custom Python code on messages.
    Similar to Node-RED's function node.
    """
    display_name = 'Function'
    icon = 'ƒ'
    category = 'function'
    color = '#E6E0F8'
    border_color = '#9F93C6'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'func',
            'label': 'Function',
            'type': 'textarea'
        },
        {
            'name': 'outputs',
            'label': 'Outputs',
            'type': 'number',
            'default': DEFAULT_CONFIG['outputs'],
            'min': 1,
            'max': 10
        }
    ]
    
    def __init__(self, node_id=None, name="function"):
        super().__init__(node_id, name)
        self.configure(self.DEFAULT_CONFIG)
    
    def configure(self, config: Dict[str, Any]):
        """Configure the node and update output_count based on outputs setting."""
        super().configure(config)
        self.output_count = self.get_config_int('outputs', 1)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Execute the function code on the incoming message.
        """
        try:
            func_code = self.config.get('func', 'return msg')
            
            # Wrap the user's code in a function to support return statements
            wrapped_code = f'''def user_function(msg, node, time):
{chr(10).join("    " + line for line in func_code.split(chr(10)))}

result = user_function(msg, node, time)
'''
            
            # Create a deep copy to avoid modifying the original and handle non-serializable objects
            try:
                msg_copy = copy.deepcopy(msg)
            except Exception:
                # If deep copy fails, use shallow copy and let user handle it
                msg_copy = msg.copy()
            
            # Create a safe execution context with helpful utilities
            context = {
                'msg': msg_copy,
                'node': self,
                'time': time,
                # Add common utilities
                'isinstance': isinstance,
                'dict': dict,
                'list': list,
                'str': str,
                'int': int,
                'float': float,
                'set': set,
                'tuple': tuple
            }
            
            # Execute the wrapped function
            exec(wrapped_code, context)
            
            # Get the result
            result = context.get('result')
            
            if result is not None:
                if isinstance(result, list):
                    # Multiple outputs
                    for idx, out_msg in enumerate(result):
                        if out_msg is not None:
                            self.send(out_msg, idx)
                else:
                    # Single output
                    self.send(result)
                    
        except Exception as e:
            # Provide more helpful error messages
            error_str = str(e)
            payload_type = type(msg.get('payload')).__name__
            
            # Add context-specific hints
            if "does not support item assignment" in error_str:
                hint = f"Hint: msg['payload'] is a {payload_type}, not a dict. "
                if payload_type in ['float', 'int', 'str', 'bool']:
                    hint += "To add an index, wrap it: msg['payload'] = {'value': msg['payload'], 'index': 0}"
                error_str = hint + " Error: " + error_str
            
            # Report error to the error system
            self.report_error(f"Function error: {error_str}")
            # Also send error downstream for debugging
            error_msg = self.create_message(
                payload={
                    'error': error_str,
                    'original_payload': msg.get('payload'),
                    'payload_type': payload_type
                },
                topic='error'
            )
            self.send(error_msg)
