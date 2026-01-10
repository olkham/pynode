"""
Message Writer Node - writes messages or message components to disk.
Supports dynamic filenames and flexible data extraction from messages.
"""

import os
import json
import pickle
import time
import base64
from datetime import datetime
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Writes messages or message components to disk. Supports JSON, binary, or text formats with dynamic filenames.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with data to write. Can write whole message or specific components.")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Status message with path, filename, bytes written, and counter.")
)
_info.add_header("Message Properties")
_info.add_bullets(
    ("msg.fname:", "Override filename from message."),
    ("msg.extension:", "Override file extension from message.")
)
_info.add_header("Data Source Options")
_info.add_bullets(
    ("whole_message:", "Write entire message object"),
    ("msg.payload:", "Write only the payload"),
    ("msg.topic:", "Write only the topic"),
    ("custom:", "Write custom message path (e.g., msg.payload.detections)")
)
_info.add_header("Naming Modes")
_info.add_bullets(
    ("Counter:", "data_0001.json, data_0002.json, ..."),
    ("Timestamp:", "data_1234567890.json (Unix timestamp)"),
    ("DateTime:", "data_2024-12-03_153045.json"),
    ("Message:", "Use msg.fname from incoming message")
)


class MessageWriterNode(BaseNode):
    """
    Message Writer node - writes messages or message components to disk.
    Supports flexible data extraction and multiple output formats.
    """
    display_name = 'Message Writer'
    icon = '📝'
    category = 'output'
    color = '#9B7CB6'
    border_color = '#6B4C7B'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    info = str(_info)
    
    DEFAULT_CONFIG = {
        'directory': './output',
        'filename': 'message',
        'extension': 'json',
        'naming_mode': 'counter',
        'counter_digits': '4',
        'overwrite': 'false',
        'create_subdirs': 'true',
        'data_source': 'whole_message',
        'custom_path': f'{MessageKeys.MSG}.{MessageKeys.PAYLOAD}',
        'output_format': 'json'
    }
    
    properties = [
        {
            'name': 'directory',
            'label': 'Output Directory',
            'type': 'text',
            'default': DEFAULT_CONFIG['directory'],
            'help': 'Directory where files will be saved (created if doesn\'t exist)'
        },
        {
            'name': 'filename',
            'label': 'Filename/Prefix',
            'type': 'text',
            'default': DEFAULT_CONFIG['filename'],
            'help': 'Filename or prefix. Can be overridden by msg.fname. Supports {timestamp}, {counter}'
        },
        {
            'name': 'extension',
            'label': 'File Extension',
            'type': 'select',
            'options': [
                {'value': 'json', 'label': '.json'},
                {'value': 'txt', 'label': '.txt'},
                {'value': 'bin', 'label': '.bin (binary)'},
                {'value': 'pkl', 'label': '.pkl (pickle)'},
                {'value': 'npy', 'label': '.npy (numpy)'},
                {'value': 'csv', 'label': '.csv'},
                {'value': 'log', 'label': '.log'}
            ],
            'default': DEFAULT_CONFIG['extension'],
            'help': 'File extension. Can be overridden by msg.extension'
        },
        {
            'name': 'naming_mode',
            'label': 'Naming Mode',
            'type': 'select',
            'options': [
                {'value': 'counter', 'label': 'Counter (message_0001.json)'},
                {'value': 'timestamp', 'label': 'Timestamp (message_1234567890.json)'},
                {'value': 'datetime', 'label': 'DateTime (message_2024-12-03_153045.json)'},
                {'value': 'message', 'label': 'From Message (msg.fname)'}
            ],
            'default': DEFAULT_CONFIG['naming_mode'],
            'help': 'How to generate filenames'
        },
        {
            'name': 'counter_digits',
            'label': 'Counter Digits',
            'type': 'text',
            'default': DEFAULT_CONFIG['counter_digits'],
            'help': 'Number of digits for counter padding (e.g., 4 = 0001, 0002, ...)'
        },
        {
            'name': 'data_source',
            'label': 'Data Source',
            'type': 'select',
            'options': [
                {'value': 'whole_message', 'label': 'Whole Message'},
                {'value': MessageKeys.PAYLOAD, 'label': f'{MessageKeys.MSG}.{MessageKeys.PAYLOAD}'},
                {'value': MessageKeys.TOPIC, 'label': f'{MessageKeys.MSG}.{MessageKeys.TOPIC}'},
                {'value': 'custom', 'label': 'Custom Path'}
            ],
            'default': DEFAULT_CONFIG['data_source'],
            'help': 'What part of the message to write'
        },
        {
            'name': 'custom_path',
            'label': 'Custom Message Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['custom_path'],
            'help': 'Custom path when data_source is "custom" (e.g., msg.payload.detections, msg.cv.image)',
            'showIf': {'data_source': 'custom'}
        },
        {
            'name': 'output_format',
            'label': 'Output Format',
            'type': 'select',
            'options': [
                {'value': 'json', 'label': 'JSON (human readable)'},
                {'value': 'json_compact', 'label': 'JSON (compact)'},
                {'value': 'pickle', 'label': 'Pickle (binary)'},
                {'value': 'numpy', 'label': 'NumPy (.npy binary)'},
                {'value': 'text', 'label': 'Text (string representation)'},
                {'value': 'raw', 'label': 'Raw (bytes as-is)'}
            ],
            'default': DEFAULT_CONFIG['output_format'],
            'help': 'How to format the data before writing'
        },
        {
            'name': 'overwrite',
            'label': 'Overwrite Existing',
            'type': 'select',
            'options': [
                {'value': 'false', 'label': 'No (skip if exists)'},
                {'value': 'true', 'label': 'Yes (overwrite)'}
            ],
            'default': DEFAULT_CONFIG['overwrite'],
            'help': 'Overwrite existing files or skip them'
        },
        {
            'name': 'create_subdirs',
            'label': 'Create Subdirectories',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes'},
                {'value': 'false', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['create_subdirs'],
            'help': 'Create directory structure if it doesn\'t exist'
        }
    ]
    
    def __init__(self, node_id=None, name="message writer"):
        super().__init__(node_id, name)
        self._counter = 0
        self._last_written = None
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Write message data to disk. Can write whole message or specific components.
        """
        try:
            # Get directory from config
            directory = self.config.get('directory', './output')
            
            # Get filename/prefix - prioritize msg.fname over config
            if 'fname' in msg:
                filename = str(msg['fname'])
            else:
                filename = self.config.get('filename', 'message')
            
            # Get extension - prioritize msg.extension over config
            if 'extension' in msg:
                extension = str(msg['extension']).lstrip('.')
            else:
                extension = self.config.get('extension', 'json')
            
            # Generate full filename based on naming mode
            naming_mode = self.config.get('naming_mode', 'counter')
            full_filename = self._generate_filename(filename, extension, naming_mode, msg)
            
            # Build full path
            full_path = os.path.join(directory, full_filename)
            
            # Create directory if needed
            create_subdirs = self.get_config_bool('create_subdirs', True)
            if create_subdirs:
                os.makedirs(directory, exist_ok=True)
            elif not os.path.exists(directory):
                self.report_error(f"Directory does not exist: {directory}")
                return
            
            # Check if file exists and handle overwrite setting
            overwrite = self.get_config_bool('overwrite', False)
            if os.path.exists(full_path) and not overwrite:
                output_msg = self.create_message(
                    payload={
                        'status': 'skipped',
                        'reason': 'file_exists',
                        'path': full_path
                    },
                    topic=msg.get(MessageKeys.TOPIC, 'MessageWriter')
                )
                self.send(output_msg)
                return
            
            # Extract data to write based on data_source setting
            data_to_write = self._extract_data(msg)
            
            if data_to_write is None:
                self.report_error("No data found to write")
                return
            
            # Write data based on output format
            bytes_written = self._write_data(full_path, data_to_write, extension)
            
            # Track last written file
            self._last_written = full_path
            
            # Send success message
            output_msg = self.create_message(
                payload={
                    'status': 'success',
                    'path': full_path,
                    'filename': full_filename,
                    'bytes': bytes_written,
                    'counter': self._counter,
                    'data_source': self.config.get('data_source', 'whole_message')
                },
                topic=msg.get(MessageKeys.TOPIC, 'MessageWriter')
            )
            self.send(output_msg)
            
        except Exception as e:
            self.report_error(f"Failed to write file: {str(e)}")
            output_msg = self.create_message(
                payload={
                    'status': 'error',
                    'error': str(e)
                },
                topic=msg.get(MessageKeys.TOPIC, 'MessageWriter/error')
            )
            self.send(output_msg)
    
    def _extract_data(self, msg: Dict[str, Any]) -> Any:
        """Extract data from message based on data_source configuration."""
        data_source = self.config.get('data_source', 'whole_message')
        
        if data_source == 'whole_message':
            return msg
        elif data_source == MessageKeys.PAYLOAD:
            return msg.get(MessageKeys.PAYLOAD)
        elif data_source == MessageKeys.TOPIC:
            return msg.get(MessageKeys.TOPIC)
        elif data_source == 'custom':
            custom_path = self.config.get('custom_path', 'msg.payload')
            return self._extract_custom_path(msg, custom_path)
        else:
            return msg.get(MessageKeys.PAYLOAD)  # Default fallback
    
    def _extract_custom_path(self, msg: Dict[str, Any], path: str) -> Any:
        """Extract data using custom path like 'msg.payload.detections'."""
        try:
            # Remove 'msg.' prefix if present
            if path.startswith('msg.'):
                path = path[4:]
            
            # Split path into components
            parts = path.split('.')
            
            # Start with the message
            current = msg
            
            # Navigate through the path
            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part)
                elif hasattr(current, part):
                    current = getattr(current, part)
                else:
                    return None
                
                if current is None:
                    return None
            
            return current
            
        except Exception as e:
            self.report_error(f"Failed to extract custom path '{path}': {str(e)}")
            return None
    
    def _generate_filename(self, base: str, extension: str, mode: str, msg: Dict[str, Any]) -> str:
        """Generate filename based on naming mode."""
        
        if mode == 'message':
            # Use filename from message as-is (msg.fname already used for base)
            return f"{base}.{extension}"
        
        elif mode == 'counter':
            # Increment counter
            self._counter += 1
            digits = self.get_config_int('counter_digits', 4)
            counter_str = str(self._counter).zfill(digits)
            
            # Replace {counter} placeholder if present, or append
            if '{counter}' in base:
                filename = base.replace('{counter}', counter_str)
            else:
                filename = f"{base}_{counter_str}"
            
            return f"{filename}.{extension}"
        
        elif mode == 'timestamp':
            # Unix timestamp
            timestamp = int(time.time() * 1000)  # milliseconds
            
            # Replace {timestamp} placeholder if present, or append
            if '{timestamp}' in base:
                filename = base.replace('{timestamp}', str(timestamp))
            else:
                filename = f"{base}_{timestamp}"
            
            return f"{filename}.{extension}"
        
        elif mode == 'datetime':
            # Human-readable datetime
            dt = datetime.now()
            datetime_str = dt.strftime('%Y%m%d_%H%M%S_%f')[:-3]  # Include milliseconds
            
            # Replace {datetime} placeholder if present, or append
            if '{datetime}' in base:
                filename = base.replace('{datetime}', datetime_str)
            else:
                filename = f"{base}_{datetime_str}"
            
            return f"{filename}.{extension}"
        
        else:
            # Default: just append extension
            return f"{base}.{extension}"
    
    def _write_data(self, path: str, data: Any, extension: str) -> int:
        """Write data to file based on output_format configuration."""
        output_format = self.config.get('output_format', 'json')
        
        try:
            if output_format == 'json':
                # Pretty-printed JSON with proper numpy array handling
                json_str = json.dumps(data, indent=2, default=self._json_serializer)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(json_str)
                return len(json_str.encode('utf-8'))
            
            elif output_format == 'json_compact':
                # Compact JSON with proper numpy array handling
                json_str = json.dumps(data, separators=(',', ':'), default=self._json_serializer)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(json_str)
                return len(json_str.encode('utf-8'))
            
            elif output_format == 'pickle':
                # Pickle binary format
                with open(path, 'wb') as f:
                    pickle.dump(data, f)
                return os.path.getsize(path)
            
            elif output_format == 'numpy':
                # NumPy binary format (.npy)
                try:
                    import numpy as np
                    if isinstance(data, np.ndarray):
                        np.save(path, data)
                        return os.path.getsize(path)
                    else:
                        # If not a numpy array, try to convert it
                        np_data = np.array(data)
                        np.save(path, np_data)
                        return os.path.getsize(path)
                except ImportError:
                    # Fallback to pickle if numpy not available
                    with open(path, 'wb') as f:
                        pickle.dump(data, f)
                    return os.path.getsize(path)
            
            elif output_format == 'text':
                # String representation
                text_data = str(data)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(text_data)
                return len(text_data.encode('utf-8'))
            
            elif output_format == 'raw':
                # Raw bytes - data must be bytes-like
                if isinstance(data, bytes):
                    with open(path, 'wb') as f:
                        f.write(data)
                    return len(data)
                elif isinstance(data, str):
                    # Convert string to bytes
                    data_bytes = data.encode('utf-8')
                    with open(path, 'wb') as f:
                        f.write(data_bytes)
                    return len(data_bytes)
                else:
                    # Check if it's a numpy array
                    try:
                        import numpy as np
                        if isinstance(data, np.ndarray):
                            # Save as raw numpy bytes
                            data_bytes = data.tobytes()
                            with open(path, 'wb') as f:
                                f.write(data_bytes)
                            return len(data_bytes)
                    except ImportError:
                        pass
                    
                    # Try to convert to bytes via pickle
                    data_bytes = pickle.dumps(data)
                    with open(path, 'wb') as f:
                        f.write(data_bytes)
                    return len(data_bytes)
            
            else:
                # Default to JSON
                json_str = json.dumps(data, indent=2, default=self._json_serializer)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(json_str)
                return len(json_str.encode('utf-8'))
        
        except Exception as e:
            # Fallback to string representation if serialization fails
            text_data = str(data)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text_data)
            return len(text_data.encode('utf-8'))
    
    def _json_serializer(self, obj):
        """Custom JSON serializer to handle numpy arrays and other special types."""
        try:
            import numpy as np
            if isinstance(obj, np.ndarray):
                # Convert numpy array to base64 string for JSON serialization
                return {
                    "_numpy_array": True,
                    "data": base64.b64encode(obj.tobytes()).decode('utf-8'),
                    "dtype": str(obj.dtype),
                    "shape": obj.shape
                }
            elif isinstance(obj, np.integer):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
        except ImportError:
            pass
        
        # Handle other types that aren't JSON serializable
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        
        # Default fallback
        return str(obj)
    
    def get_counter(self) -> int:
        """Get current counter value."""
        return self._counter
    
    def reset_counter(self):
        """Reset counter to 0."""
        self._counter = 0
    
    def get_last_written(self):
        """Get path of last written file."""
        return self._last_written