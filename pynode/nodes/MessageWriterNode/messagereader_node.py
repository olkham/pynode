"""
Message Reader Node - reads messages or data from disk files.
Supports reading various formats written by MessageWriterNode.
"""

import os
import json
import pickle
import base64
import glob
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Reads messages or data from disk files. Supports JSON, binary, and text formats with batch reading capabilities.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Optional trigger message. If provided, reads files based on msg.path or configured directory.")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Message containing the read data. For batch reading, outputs multiple messages.")
)
_info.add_header("Message Properties")
_info.add_bullets(
    ("msg.path:", "Specific file path to read (overrides directory setting)"),
    ("msg.pattern:", "File pattern for batch reading (e.g., '*.json')")
)
_info.add_header("Reading Modes")
_info.add_bullets(
    ("single_file:", "Read one specific file"),
    ("batch_pattern:", "Read multiple files matching a pattern"),
    ("watch_directory:", "Monitor directory for new files"),
    ("latest_file:", "Read the most recently modified file")
)
_info.add_header("Input Formats")
_info.add_bullets(
    ("auto:", "Auto-detect format from file extension"),
    ("json:", "JSON format (with numpy array reconstruction)"),
    ("pickle:", "Python pickle format"),
    ("numpy:", "NumPy .npy binary format"),
    ("text:", "Plain text format")
)


class MessageReaderNode(BaseNode):
    """
    Message Reader node - reads messages or data from disk files.
    Companion to MessageWriterNode with format reconstruction capabilities.
    """
    display_name = 'Message Reader'
    icon = '📖'
    category = 'input'
    color = '#6B9BD2'
    border_color = '#4A7BA7'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    ui_component = 'button'
    ui_component_config = {
        'icon': '▶',
        'action': 'read_files',
        'tooltip': 'Read Files'
    }
    info = str(_info)
    
    DEFAULT_CONFIG = {
        'directory': './output',
        'filename_pattern': '*.json',
        'reading_mode': 'single_file',
        'specific_file': '',
        'input_format': 'auto',
        'sort_order': 'name',
        'max_files': '10',
        'include_metadata': 'true',
        'recursive': 'false',
        'output_structure': 'auto_detect'
    }
    
    properties = [
        {
            'name': 'directory',
            'label': 'Directory',
            'type': 'text',
            'default': DEFAULT_CONFIG['directory'],
            'help': 'Directory to read files from'
        },
        {
            'name': 'reading_mode',
            'label': 'Reading Mode',
            'type': 'select',
            'options': [
                {'value': 'single_file', 'label': 'Single File'},
                {'value': 'batch_pattern', 'label': 'Batch (Pattern)'},
                {'value': 'latest_file', 'label': 'Latest File'},
                {'value': 'all_files', 'label': 'All Files'}
            ],
            'default': DEFAULT_CONFIG['reading_mode'],
            'help': 'How to select files to read'
        },
        {
            'name': 'specific_file',
            'label': 'Specific File',
            'type': 'text',
            'default': DEFAULT_CONFIG['specific_file'],
            'help': f'Specific filename when reading_mode is "single_file" - leave blank to use {MessageKeys.MSG}.{MessageKeys.PAYLOAD}.filename',
            'showIf': {'reading_mode': 'single_file'}
        },
        {
            'name': 'filename_pattern',
            'label': 'Filename Pattern',
            'type': 'text',
            'default': DEFAULT_CONFIG['filename_pattern'],
            'help': 'Pattern to match files (e.g., *.json, message_*.txt)',
            'showIf': {'reading_mode': ['batch_pattern', 'latest_file', 'all_files']}
        },
        {
            'name': 'input_format',
            'label': 'Input Format',
            'type': 'select',
            'options': [
                {'value': 'auto', 'label': 'Auto-detect'},
                {'value': 'json', 'label': 'JSON'},
                {'value': 'pickle', 'label': 'Pickle'},
                {'value': 'numpy', 'label': 'NumPy (.npy)'},
                {'value': 'text', 'label': 'Text'},
                {'value': 'raw', 'label': 'Raw bytes'}
            ],
            'default': DEFAULT_CONFIG['input_format'],
            'help': 'Format of the input files'
        },
        {
            'name': 'sort_order',
            'label': 'Sort Order',
            'type': 'select',
            'options': [
                {'value': 'name', 'label': 'Name'},
                {'value': 'modified', 'label': 'Modified Time'},
                {'value': 'size', 'label': 'File Size'}
            ],
            'default': DEFAULT_CONFIG['sort_order'],
            'help': 'How to sort files for batch reading',
            'showIf': {'reading_mode': ['batch_pattern', 'latest_file', 'all_files']}
        },
        {
            'name': 'max_files',
            'label': 'Max Files',
            'type': 'text',
            'default': DEFAULT_CONFIG['max_files'],
            'help': 'Maximum number of files to read in batch mode',
            'showIf': {'reading_mode': ['batch_pattern', 'all_files']}
        },
        {
            'name': 'include_metadata',
            'label': 'Include File Metadata',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes'},
                {'value': 'false', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['include_metadata'],
            'help': 'Include file metadata (size, modified time) in output'
        },
        {
            'name': 'recursive',
            'label': 'Recursive Search',
            'type': 'select',
            'options': [
                {'value': 'false', 'label': 'No'},
                {'value': 'true', 'label': 'Yes'}
            ],
            'default': DEFAULT_CONFIG['recursive'],
            'help': 'Search subdirectories recursively'
        },
        {
            'name': 'output_structure',
            'label': 'Output Structure',
            'type': 'select',
            'options': [
                {'value': 'auto_detect', 'label': 'Auto-detect (smart reconstruction)'},
                {'value': 'wrap_in_data', 'label': f'Always wrap in {MessageKeys.MSG}.{MessageKeys.PAYLOAD}.data'},
                {'value': 'direct_payload', 'label': f'Direct to {MessageKeys.MSG}.{MessageKeys.PAYLOAD}'},
                {'value': 'reconstruct_message', 'label': 'Reconstruct whole message'}
            ],
            'default': DEFAULT_CONFIG['output_structure'],
            'help': 'How to structure the read data in the output message'
        }
    ]
    
    def __init__(self, node_id=None, name="message reader"):
        super().__init__(node_id, name)
        self._last_read_time = None
        self._file_cache = {}
    
    def _create_output_message(self, data, original_filename=None):
        """Create output message based on output_structure setting."""
        output_structure = self.config.get('output_structure', 'auto_detect')
        
        if output_structure == 'auto_detect':
            # Try to detect if this was a whole message or just payload
            if (isinstance(data, dict) and 
                (MessageKeys.PAYLOAD in data or MessageKeys.TOPIC in data or MessageKeys.MSGID in data) and
                not ('data' in data and len(data) == 1)):  # Not just wrapped data
                # Looks like a whole message - reconstruct it
                msg = data.copy()
                if original_filename and 'filename' not in msg:
                    msg['filename'] = original_filename
                return msg
            else:
                # Looks like payload data - put directly in msg.payload
                return self.create_message(payload=data, filename=original_filename)
        
        elif output_structure == 'reconstruct_message':
            # Always try to use data as whole message
            if isinstance(data, dict):
                msg = data.copy()
                if original_filename and 'filename' not in msg:
                    msg['filename'] = original_filename
                return msg
            else:
                return self.create_message(payload=data, filename=original_filename)
        
        elif output_structure == 'direct_payload':
            # Always put data directly in payload
            return self.create_message(payload=data, filename=original_filename)
        
        else:  # wrap_in_data (original behavior)
            # Always wrap in msg.payload.data
            return self.create_message(
                payload={'data': data, 'filename': original_filename}
            )
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Read files based on configuration or message content.
        """
        try:
            # Get directory and file info from message or config
            if 'path' in msg:
                # Specific file path provided in message
                file_path = msg['path']
                if os.path.isfile(file_path):
                    self._read_single_file(file_path, msg)
                else:
                    self.report_error(f"File not found: {file_path}")
            else:
                # Use configured reading mode
                self._read_files_by_mode(msg)
                
        except Exception as e:
            self.report_error(f"Failed to read files: {str(e)}")
            output_msg = self.create_message(
                payload={
                    'status': 'error',
                    'error': str(e)
                },
                topic=msg.get(MessageKeys.TOPIC, 'MessageReader/error')
            )
            self.send(output_msg)
    
    def read_files(self):
        """Action method for UI button - read files without input message."""
        empty_msg = self.create_message(payload={}, topic='MessageReader/action')
        self._read_files_by_mode(empty_msg)
    
    def _read_files_by_mode(self, trigger_msg: Dict[str, Any]):
        """Read files based on configured reading mode."""
        reading_mode = self.config.get('reading_mode', 'single_file')
        directory = self.config.get('directory', './output')
        
        if not os.path.exists(directory):
            self.report_error(f"Directory does not exist: {directory}")
            return
        
        if reading_mode == 'single_file':
            filename = self.config.get('specific_file', '')
            
            # If filename is blank, try to get it from incoming message
            if not filename:
                payload = trigger_msg.get(MessageKeys.PAYLOAD, {})
                if isinstance(payload, dict) and 'filename' in payload:
                    filename = payload['filename']
                else:
                    filename = 'message_0001.json'  # Default fallback
            
            file_path = os.path.join(directory, filename)
            self._read_single_file(file_path, trigger_msg)
            
        elif reading_mode == 'batch_pattern':
            self._read_batch_files(directory, trigger_msg)
            
        elif reading_mode == 'latest_file':
            self._read_latest_file(directory, trigger_msg)
            
        elif reading_mode == 'all_files':
            self._read_all_files(directory, trigger_msg)
    
    def _read_single_file(self, file_path: str, trigger_msg: Dict[str, Any]):
        """Read a single file and send as message."""
        try:
            if not os.path.exists(file_path):
                self.report_error(f"File not found: {file_path}")
                return
            
            data = self._read_file_data(file_path)
            filename = os.path.basename(file_path)
            
            # Use helper to create properly structured message
            output_msg = self._create_output_message(data, filename)
            
            # Add metadata if requested
            if self.get_config_bool('include_metadata', True):
                metadata = self._get_file_metadata(file_path)
                if MessageKeys.PAYLOAD in output_msg:
                    if isinstance(output_msg[MessageKeys.PAYLOAD], dict):
                        output_msg[MessageKeys.PAYLOAD]['metadata'] = metadata
                    else:
                        output_msg['metadata'] = metadata
                else:
                    output_msg['metadata'] = metadata
            
            # Preserve topic and add source info
            output_msg[MessageKeys.TOPIC] = trigger_msg.get(MessageKeys.TOPIC, 'MessageReader')
            output_msg['source_file'] = file_path
            output_msg['reading_mode'] = 'single_file'
            
            self.send(output_msg)
            
        except Exception as e:
            self.report_error(f"Failed to read file {file_path}: {str(e)}")
    
    def _read_batch_files(self, directory: str, trigger_msg: Dict[str, Any]):
        """Read multiple files matching pattern."""
        pattern = self.config.get('filename_pattern', '*.json')
        max_files = self.get_config_int('max_files', 10)
        
        file_list = self._get_file_list(directory, pattern)
        
        if not file_list:
            output_msg = self.create_message(
                payload={
                    'status': 'no_files',
                    'pattern': pattern,
                    'directory': directory
                },
                topic=trigger_msg.get(MessageKeys.TOPIC, 'MessageReader')
            )
            self.send(output_msg)
            return
        
        # Limit number of files
        files_to_read = file_list[:max_files]
        
        for i, file_path in enumerate(files_to_read):
            try:
                data = self._read_file_data(file_path)
                filename = os.path.basename(file_path)
                
                # Use helper to create properly structured message
                output_msg = self._create_output_message(data, filename)
                
                # Add batch-specific metadata
                if MessageKeys.PAYLOAD in output_msg:
                    if isinstance(output_msg[MessageKeys.PAYLOAD], dict):
                        output_msg[MessageKeys.PAYLOAD]['batch_index'] = i
                        output_msg[MessageKeys.PAYLOAD]['batch_total'] = len(files_to_read)
                        if self.get_config_bool('include_metadata', True):
                            output_msg[MessageKeys.PAYLOAD]['metadata'] = self._get_file_metadata(file_path)
                    else:
                        # For direct payload mode, add batch info as top-level properties
                        output_msg['batch_index'] = i
                        output_msg['batch_total'] = len(files_to_read)
                        if self.get_config_bool('include_metadata', True):
                            output_msg['metadata'] = self._get_file_metadata(file_path)
                
                # Preserve topic and add source info
                output_msg[MessageKeys.TOPIC] = trigger_msg.get(MessageKeys.TOPIC, 'MessageReader')
                output_msg['source_file'] = file_path
                output_msg['reading_mode'] = 'batch_pattern'
                
                self.send(output_msg)
                
            except Exception as e:
                self.report_error(f"Failed to read file {file_path}: {str(e)}")
    
    def _read_latest_file(self, directory: str, trigger_msg: Dict[str, Any]):
        """Read the most recently modified file."""
        pattern = self.config.get('filename_pattern', '*.json')
        file_list = self._get_file_list(directory, pattern, sort_by='modified')
        
        if not file_list:
            output_msg = self.create_message(
                payload={
                    'status': 'no_files',
                    'pattern': pattern,
                    'directory': directory
                },
                topic=trigger_msg.get(MessageKeys.TOPIC, 'MessageReader')
            )
            self.send(output_msg)
            return
        
        latest_file = file_list[0]  # First in list is most recent
        self._read_single_file(latest_file, trigger_msg)
    
    def _read_all_files(self, directory: str, trigger_msg: Dict[str, Any]):
        """Read all files in directory (respecting max_files limit)."""
        self.config['filename_pattern'] = '*'  # Override pattern for all files
        self._read_batch_files(directory, trigger_msg)
    
    def _get_file_list(self, directory: str, pattern: str, sort_by: Optional[str] = None) -> List[str]:
        """Get list of files matching pattern, sorted by specified criteria."""
        recursive = self.get_config_bool('recursive', False)
        
        if recursive:
            # Recursive search
            search_pattern = os.path.join(directory, '**', pattern)
            file_list = glob.glob(search_pattern, recursive=True)
        else:
            # Non-recursive search
            search_pattern = os.path.join(directory, pattern)
            file_list = glob.glob(search_pattern)
        
        # Filter to only files (not directories)
        file_list = [f for f in file_list if os.path.isfile(f)]
        
        # Sort files
        sort_order = sort_by or self.config.get('sort_order', 'name')
        
        if sort_order == 'modified':
            file_list.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        elif sort_order == 'size':
            file_list.sort(key=lambda x: os.path.getsize(x), reverse=True)
        else:  # name
            file_list.sort()
        
        return file_list
    
    def _read_file_data(self, file_path: str) -> Any:
        """Read and parse file data based on format."""
        input_format = self.config.get('input_format', 'auto')
        
        # Auto-detect format from extension
        if input_format == 'auto':
            _, ext = os.path.splitext(file_path)
            ext = ext.lower().lstrip('.')
            
            if ext == 'json':
                input_format = 'json'
            elif ext in ['pkl', 'pickle']:
                input_format = 'pickle'
            elif ext == 'npy':
                input_format = 'numpy'
            elif ext in ['txt', 'log', 'csv']:
                input_format = 'text'
            else:
                input_format = 'raw'
        
        # Read based on format
        if input_format == 'json':
            return self._read_json_file(file_path)
        elif input_format == 'pickle':
            return self._read_pickle_file(file_path)
        elif input_format == 'numpy':
            return self._read_numpy_file(file_path)
        elif input_format == 'text':
            return self._read_text_file(file_path)
        elif input_format == 'raw':
            return self._read_raw_file(file_path)
        else:
            return self._read_text_file(file_path)  # Default fallback
    
    def _read_json_file(self, file_path: str) -> Any:
        """Read JSON file with numpy array reconstruction."""
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Recursively reconstruct numpy arrays
        return self._reconstruct_numpy_arrays(data)
    
    def _read_pickle_file(self, file_path: str) -> Any:
        """Read pickle file."""
        with open(file_path, 'rb') as f:
            return pickle.load(f)
    
    def _read_numpy_file(self, file_path: str) -> Any:
        """Read numpy .npy file."""
        try:
            import numpy as np
            return np.load(file_path)
        except ImportError:
            # Fallback to raw bytes if numpy not available
            return self._read_raw_file(file_path)
    
    def _read_text_file(self, file_path: str) -> str:
        """Read text file."""
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def _read_raw_file(self, file_path: str) -> bytes:
        """Read raw bytes."""
        with open(file_path, 'rb') as f:
            return f.read()
    
    def _reconstruct_numpy_arrays(self, data: Any) -> Any:
        """Recursively reconstruct numpy arrays from JSON serialization."""
        if isinstance(data, dict):
            if data.get('_numpy_array'):
                # This is a serialized numpy array
                try:
                    import numpy as np
                    array_bytes = base64.b64decode(data['data'])
                    dtype = np.dtype(data['dtype'])
                    shape = tuple(data['shape'])
                    return np.frombuffer(array_bytes, dtype=dtype).reshape(shape)
                except ImportError:
                    # Return as dict if numpy not available
                    return data
                except Exception as e:
                    self.report_error(f"Failed to reconstruct numpy array: {str(e)}")
                    return data
            else:
                # Recursively process dictionary
                return {key: self._reconstruct_numpy_arrays(value) for key, value in data.items()}
        elif isinstance(data, list):
            # Recursively process list
            return [self._reconstruct_numpy_arrays(item) for item in data]
        else:
            # Return as-is for other types
            return data
    
    def _get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """Get file metadata."""
        stat = os.stat(file_path)
        return {
            'size': stat.st_size,
            'modified': stat.st_mtime,
            'modified_iso': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'basename': os.path.basename(file_path),
            'extension': os.path.splitext(file_path)[1]
        }