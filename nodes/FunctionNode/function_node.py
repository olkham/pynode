"""
Function node - executes custom Python code on messages.
Similar to Node-RED's function node.
"""

import time
from typing import Any, Dict
from base_node import BaseNode


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
        }
    ]
    
    def __init__(self, node_id=None, name="function"):
        super().__init__(node_id, name)
        self.configure({
            'func': 'msg["payload"] = msg["payload"]\nreturn msg',
            'outputs': 1
        })
    
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
            
            # Create a safe execution context
            context = {
                'msg': msg.copy(),
                'node': self,
                'time': time
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
            error_msg = self.create_message(
                payload={'error': str(e), 'original_payload': msg.get('payload')},
                topic='error'
            )
            self.send(error_msg)
