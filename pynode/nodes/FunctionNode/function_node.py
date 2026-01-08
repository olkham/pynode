"""
Function node - executes custom Python code on messages.
Similar to Node-RED's function node.
"""

import time
import copy
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Executes custom Python code on incoming messages. Similar to Node-RED's function node.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Any message to process.")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0-N:", "Processed message(s). Configure number of outputs in properties.")
)
_info.add_header("Available Variables")
_info.add_bullets(
    ("msg:", "The incoming message dictionary."),
    ("node:", "Reference to this node (for node.send(), node.report_error())."),
    ("time:", "Python time module.")
)
_info.add_header("Example")
_info.add_code(f"msg['{MessageKeys.PAYLOAD}'] = msg['{MessageKeys.PAYLOAD}'] * 2\nreturn msg").text("Doubles the payload value and returns the modified message.").end()
_info.add_header("Multiple Outputs")
_info.add_code(f"return [msg, None, {{'{MessageKeys.PAYLOAD}': 'alt'}}]").text("Returns array to send to different outputs. None skips that output.").end()


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
    info = str(_info)
    
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
            'default': 1,
            'min': 1,
            'max': 10
        }
    ]
    
    def __init__(self, node_id=None, name="function"):
        super().__init__(node_id, name)
    
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
                    
        except SyntaxError as e:
            # Provide helpful syntax error messages with line numbers
            line_num = e.lineno - 1 if e.lineno else 0  # Adjust for wrapper function
            user_lines = func_code.split('\n')
            
            error_context = f"Syntax error on line {line_num}: {e.msg}\n"
            if 0 <= line_num - 1 < len(user_lines):
                error_context += f"  {line_num}: {user_lines[line_num - 1]}\n"
            if 0 <= line_num < len(user_lines):
                error_context += f"→ {line_num + 1}: {user_lines[line_num]}\n"
            if line_num + 1 < len(user_lines):
                error_context += f"  {line_num + 2}: {user_lines[line_num + 1]}\n"
            
            self.report_error(error_context)
            error_msg = self.create_message(
                payload={'error': error_context, 'type': 'SyntaxError'},
                topic='error'
            )
            self.send(error_msg)
            
        except Exception as e:
            # Provide more helpful error messages
            error_str = str(e)
            payload_type = type(msg.get(MessageKeys.PAYLOAD)).__name__
            
            # Add context-specific hints
            if "does not support item assignment" in error_str:
                hint = f"Hint: msg['{MessageKeys.PAYLOAD}'] is a {payload_type}, not a dict. "
                if payload_type in ['float', 'int', 'str', 'bool']:
                    hint += f"To add an index, wrap it: msg['{MessageKeys.PAYLOAD}'] = {{'value': msg['{MessageKeys.PAYLOAD}'], 'index': 0}}"
                error_str = hint + " Error: " + error_str
            
            # Report error to the error system
            self.report_error(f"Function error: {error_str}")
            # Also send error downstream for debugging
            error_msg = self.create_message(
                payload={
                    'error': error_str,
                    'original_payload': msg.get(MessageKeys.PAYLOAD),
                    'payload_type': payload_type
                },
                topic='error'
            )
            self.send(error_msg)
