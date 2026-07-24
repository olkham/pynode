"""
Function node - executes custom Python code on messages.
Similar to Node-RED's function node.
"""

import time
import copy
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys


class DotDict(dict):
    """A ``dict`` that also supports attribute access to its keys.

    Lets Function-node code use the cleaner ``msg.payload`` / ``msg.topic``
    style in addition to ``msg['payload']``. It is a real ``dict`` subclass,
    so everything downstream (JSON, ``send()``'s copy, other nodes) keeps
    treating it as an ordinary message dict.

    Notes / limitations:

    * Nested dicts are wrapped too (see :func:`_to_dotdict`), so chained access
      like ``msg.payload.crop`` and assignment ``msg.payload.crop = [..]`` both
      read/write the same value as ``msg['payload']['crop']``.
    * A missing attribute raises ``AttributeError`` (so ``hasattr`` works),
      matching normal Python objects.
    * Keys that collide with real ``dict`` methods (``items``, ``get``,
      ``keys``, ``update``, ...) stay reachable only via ``msg['items']`` -
      attribute lookup returns the method, not the value.
    """

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        try:
            del self[name]
        except KeyError:
            raise AttributeError(name)


def _to_dotdict(value: Any) -> Any:
    """Recursively wrap dicts (including those nested in lists/tuples) as
    :class:`DotDict` so attribute access works at every level.

    New containers are built, so the source object is never mutated. Non-dict
    leaves (numpy arrays, scalars, strings, ...) are returned unchanged - a raw
    video-frame payload is passed through, not copied.
    """
    if isinstance(value, dict):
        return DotDict((k, _to_dotdict(v)) for k, v in value.items())
    if isinstance(value, list):
        return [_to_dotdict(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_to_dotdict(v) for v in value)
    return value


# Ready-made snippets offered by the "Load an example" dropdown in the
# properties panel. Each is a complete function body (ending in ``return``).
# They use the cleaner ``msg.payload`` style; ``msg['payload']`` works too.
#
# 'outputs' is the output count the snippet needs. The UI applies it to the
# node when the example is picked, so a two-output template really gives the
# node two output ports. Every example states it so applying a template fully
# defines the node's shape (and switching back from a multi-output template
# restores a single output).
FUNCTION_EXAMPLES = [
    {'label': 'Pass the message through',
     'outputs': 1,
     'code': 'return msg'},
    {'label': 'Convert payload to an integer',
     'outputs': 1,
     'code': 'msg.payload = int(msg.payload)\nreturn msg'},
    {'label': 'Convert payload to a float',
     'outputs': 1,
     'code': 'msg.payload = float(msg.payload)\nreturn msg'},
    {'label': 'Convert payload to text',
     'outputs': 1,
     'code': 'msg.payload = str(msg.payload)\nreturn msg'},
    {'label': 'Multiply payload by 2',
     'outputs': 1,
     'code': 'msg.payload = msg.payload * 2\nreturn msg'},
    {'label': 'Uppercase a text payload',
     'outputs': 1,
     'code': 'msg.payload = str(msg.payload).upper()\nreturn msg'},
    {'label': 'Set the topic',
     'outputs': 1,
     'code': "msg.topic = 'my_topic'\nreturn msg"},
    {'label': 'Wrap the value in an object',
     'outputs': 1,
     'code': "msg.payload = {'value': msg.payload}\nreturn msg"},
    {'label': 'Add a timestamp',
     'outputs': 1,
     'code': "msg.payload = {'value': msg.payload, 'time': time.time()}\n"
             "return msg"},
    {'label': 'Read a nested field (payload must be a dict)',
     'outputs': 1,
     'code': '# msg.payload.bbox is the same as msg["payload"]["bbox"]\n'
             'msg.payload = msg.payload.bbox\nreturn msg'},
    {'label': 'Filter: drop messages below a threshold',
     'outputs': 1,
     'code': '# returning None drops the message (nothing is sent)\n'
             'if msg.payload < 10:\n    return None\nreturn msg'},
    {'label': 'Send to two outputs',
     'outputs': 2,
     'code': "# each list item goes to the matching output; None skips one\n"
             "return [msg, {'payload': 'copy'}]"},
    {'label': 'Route to one of two outputs',
     'outputs': 2,
     'code': '# send out of output 1 when big, output 2 otherwise\n'
             'if msg.payload > 100:\n    return [msg, None]\n'
             'return [None, msg]'},
    {'label': 'Count messages (node keeps state between calls)',
     'outputs': 1,
     'code': '# node persists across messages, so attributes stick\n'
             'node.count = getattr(node, "count", 0) + 1\n'
             'msg.payload = node.count\nreturn msg'},
]

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
    ("msg:", "The incoming message. Use msg.payload or msg['payload'] - both work."),
    ("node:", "Reference to this node; it persists between messages (e.g. node.count)."),
    ("time:", "Python time module.")
)
_info.add_header("Message Access")
_info.add_text("Read and write message fields either way:")
_info.add_bullets(
    ("Attribute style:", "msg.payload, msg.topic, msg.payload.bbox (cleaner)."),
    ("Dictionary style:", "msg['payload'], msg['topic'] (always available)."),
)
_info.add_text("Attribute style works on nested dicts too, so msg.payload.crop reads and writes the same value as msg['payload']['crop'].")
_info.add_header("Examples")
_info.add_text("Pick a template from the 'Load an example' dropdown to drop a ready-made snippet into the editor.")
_info.add_code("msg.payload = int(msg.payload)").text("converts the payload to an integer;").end()
_info.add_code("return msg").text("passes the message on.").end()
_info.add_header("Multiple Outputs")
_info.add_code("return [msg, None, {'payload': 'alt'}]").text("Returns a list to send to different outputs. None skips that output.").end()


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
            'name': 'examples',
            'label': 'Load an example',
            'type': 'code-examples',
            'target': 'func',
            'options': FUNCTION_EXAMPLES,
            'help': 'Pick a template to drop it into the function editor below.'
        },
        {
            'name': 'func',
            'label': 'Function',
            'type': 'textarea',
            'default': 'return msg',
            'placeholder': 'msg.payload = int(msg.payload)\nreturn msg'
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

            # Wrap dicts as DotDict so user code can use the cleaner attribute
            # style (msg.payload, msg.payload.crop) as well as msg['payload'].
            # DotDict is a plain dict subclass, so the returned message stays a
            # normal dict for every downstream node.
            msg_copy = _to_dotdict(msg_copy)
            
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
