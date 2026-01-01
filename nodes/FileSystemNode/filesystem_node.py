"""
File System Node - writes image frames or data to disk.
Supports dynamic filenames from messages or static configuration.
"""

import os
import base64
import time
from datetime import datetime
from typing import Any, Dict
from nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Writes image frames or data to disk. Supports dynamic filenames with counter, timestamp, or datetime patterns.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with payload containing data to write. Images should be base64 encoded or numpy arrays.")
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
_info.add_header("Naming Modes")
_info.add_bullets(
    ("Counter:", "frame_0001.jpg, frame_0002.jpg, ..."),
    ("Timestamp:", "frame_1234567890.jpg (Unix timestamp)"),
    ("DateTime:", "frame_2024-12-03_153045.jpg"),
    ("Message:", "Use msg.fname from incoming message")
)


class FileSystemNode(BaseNode):
    """
    File System node - writes image frames or data to disk.
    Supports dynamic filenames and extensions from messages or properties.
    """
    display_name = 'File System'
    icon = '💾'
    category = 'output'
    color = '#87A980'
    border_color = '#5F7858'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    info = str(_info)
    
    DEFAULT_CONFIG = {
        'directory': './output',
        'filename': 'frame',
        'extension': 'jpg',
        'naming_mode': 'counter',
        'counter_digits': '4',
        'overwrite': 'false',
        'create_subdirs': 'true'
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
                {'value': 'jpg', 'label': '.jpg'},
                {'value': 'png', 'label': '.png'},
                {'value': 'bmp', 'label': '.bmp'},
                {'value': 'txt', 'label': '.txt'},
                {'value': 'json', 'label': '.json'},
                {'value': 'bin', 'label': '.bin (binary)'}
            ],
            'default': DEFAULT_CONFIG['extension'],
            'help': 'File extension. Can be overridden by msg.extension'
        },
        {
            'name': 'naming_mode',
            'label': 'Naming Mode',
            'type': 'select',
            'options': [
                {'value': 'counter', 'label': 'Counter (frame_0001.jpg)'},
                {'value': 'timestamp', 'label': 'Timestamp (frame_1234567890.jpg)'},
                {'value': 'datetime', 'label': 'DateTime (frame_2024-12-03_153045.jpg)'},
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
    
    def __init__(self, node_id=None, name="file system"):
        super().__init__(node_id, name)
        self._counter = 0
        self._last_written = None
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Write data to disk. Expects msg.payload to contain the data to write.
        For images, payload should be base64 encoded string or raw bytes.
        """
        try:
            # Get directory from config
            directory = self.config.get('directory', './output')
            
            # Get filename/prefix - prioritize msg.fname over config
            if 'fname' in msg:
                filename = str(msg['fname'])
            else:
                filename = self.config.get('filename', 'frame')
            
            # Get extension - prioritize msg.extension over config
            if 'extension' in msg:
                extension = str(msg['extension']).lstrip('.')
            else:
                extension = self.config.get('extension', 'jpg')
            
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
                    topic=msg.get('topic', 'filesystem')
                )
                self.send(output_msg)
                return
            
            # Get payload data
            payload = msg.get('payload')
            if payload is None:
                self.report_error("No payload in message")
                return
            
            # Write data based on type
            bytes_written = self._write_data(full_path, payload, extension)
            
            # Track last written file
            self._last_written = full_path
            
            # Send success message
            output_msg = self.create_message(
                payload={
                    'status': 'success',
                    'path': full_path,
                    'filename': full_filename,
                    'bytes': bytes_written,
                    'counter': self._counter
                },
                topic=msg.get('topic', 'filesystem')
            )
            self.send(output_msg)
            
        except Exception as e:
            self.report_error(f"Failed to write file: {str(e)}")
            output_msg = self.create_message(
                payload={
                    'status': 'error',
                    'error': str(e)
                },
                topic=msg.get('topic', 'filesystem/error')
            )
            self.send(output_msg)
    
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
    
    def _write_data(self, path: str, payload: Any, extension: str) -> int:
        """Write data to file based on payload type and extension."""
        
        # Try to decode as image using BaseNode helper (handles msg.payload.image format)
        if extension in ['jpg', 'jpeg', 'png', 'bmp']:
            try:
                import cv2
                image, format_type = self.decode_image(payload)
                
                if image is not None:
                    # Encode to requested format
                    if extension in ['jpg', 'jpeg']:
                        ret, buffer = cv2.imencode('.jpg', image)
                    elif extension == 'png':
                        ret, buffer = cv2.imencode('.png', image)
                    elif extension == 'bmp':
                        ret, buffer = cv2.imencode('.bmp', image)
                    else:
                        ret = False
                    
                    if ret:
                        # Convert numpy array to bytes
                        buffer_bytes = buffer.tobytes()
                        with open(path, 'wb') as f:
                            f.write(buffer_bytes)
                        return len(buffer_bytes)
            except ImportError:
                pass  # cv2 not available, fall through to other methods
            except Exception as e:
                # If decode fails, try other methods
                pass
        
        # Handle raw bytes
        if isinstance(payload, bytes):
            with open(path, 'wb') as f:
                f.write(payload)
            return len(payload)
        
        # Handle text/string data
        elif isinstance(payload, str):
            if extension in ['txt', 'json', 'csv', 'log']:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(payload)
                return len(payload.encode('utf-8'))
            else:
                # Write as text for other extensions
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(payload)
                return len(payload.encode('utf-8'))
        
        # Handle JSON-serializable data (including dicts that aren't images)
        else:
            import json
            if extension == 'json':
                json_str = json.dumps(payload, indent=2)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(json_str)
                return len(json_str.encode('utf-8'))
            else:
                # For non-JSON extensions, convert to string
                data_str = str(payload)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(data_str)
                return len(data_str.encode('utf-8'))
    
    def get_counter(self) -> int:
        """Get current counter value."""
        return self._counter
    
    def reset_counter(self):
        """Reset counter to 0."""
        self._counter = 0
    
    def get_last_written(self):
        """Get path of last written file."""
        return self._last_written
