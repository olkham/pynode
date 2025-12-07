"""
Sync Node - buffers messages based on an index and releases them on command.
Useful for synchronizing multiple message streams or batch processing.
"""

from typing import Any, Dict, List
from nodes.base_node import BaseNode


class SyncNode(BaseNode):
    """
    Sync node - buffers messages by index and releases them on command.
    Messages are stored until a "release" payload is received.
    """
    display_name = 'Sync'
    icon = '🔄'
    category = 'logic'
    color = '#E2D96E'
    border_color = '#B8AF4A'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'index_property': 'index',
        'release_payload': 'release',
        'output_mode': 'sequential',
        'sort_order': 'ascending',
        'clear_on_release': 'true',
        'max_buffer_size': '1000',
        'allow_duplicates': 'false'
    }
    
    properties = [
        {
            'name': 'index_property',
            'label': 'Index Property',
            'type': 'text',
            'default': DEFAULT_CONFIG['index_property'],
            'help': 'Property name containing the message index (e.g., "index", "id", "sequence")'
        },
        {
            'name': 'release_payload',
            'label': 'Release Payload',
            'type': 'text',
            'default': DEFAULT_CONFIG['release_payload'],
            'help': 'Payload value that triggers release (default: "release")'
        },
        {
            'name': 'output_mode',
            'label': 'Output Mode',
            'type': 'select',
            'options': [
                {'value': 'sequential', 'label': 'Sequential (one by one)'},
                {'value': 'array', 'label': 'Array (all at once)'}
            ],
            'default': DEFAULT_CONFIG['output_mode'],
            'help': 'How to output buffered messages'
        },
        {
            'name': 'sort_order',
            'label': 'Sort Order',
            'type': 'select',
            'options': [
                {'value': 'ascending', 'label': 'Ascending (0, 1, 2, ...)'},
                {'value': 'descending', 'label': 'Descending (..., 2, 1, 0)'},
                {'value': 'none', 'label': 'None (arrival order)'}
            ],
            'default': DEFAULT_CONFIG['sort_order'],
            'help': 'How to sort messages before release',
            'showIf': {'output_mode': 'sequential'}
        },
        {
            'name': 'clear_on_release',
            'label': 'Clear After Release',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes (clear buffer)'},
                {'value': 'false', 'label': 'No (keep buffer)'}
            ],
            'default': DEFAULT_CONFIG['clear_on_release'],
            'help': 'Clear buffer after releasing messages'
        },
        {
            'name': 'max_buffer_size',
            'label': 'Max Buffer Size',
            'type': 'text',
            'default': DEFAULT_CONFIG['max_buffer_size'],
            'help': 'Maximum number of messages to buffer (0 = unlimited)'
        },
        {
            'name': 'allow_duplicates',
            'label': 'Allow Duplicate Indices',
            'type': 'select',
            'options': [
                {'value': 'false', 'label': 'No (keep first)'},
                {'value': 'true', 'label': 'Yes (overwrite with latest)'}
            ],
            'default': DEFAULT_CONFIG['allow_duplicates'],
            'help': 'Allow multiple messages for the same index (false = keep first, true = keep latest)'
        }
    ]
    
    def __init__(self, node_id=None, name="sync"):
        super().__init__(node_id, name)
        # Buffer to store messages: {index: msg}
        self._buffer: Dict[Any, Dict[str, Any]] = {}
        # Track arrival order for non-sorted output
        self._arrival_order: List[Any] = []
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Buffer message by index or release buffered messages.
        """
        try:
            payload = msg.get('payload')
            release_trigger = self.config.get('release_payload', 'release')
            
            # Check if this is a release command
            if payload == release_trigger:
                self._release_messages(msg)
                return
            
            # Otherwise, buffer the message
            index_property = self.config.get('index_property', 'index')
            
            # Get index from message
            if index_property in msg:
                msg_index = msg[index_property]
            else:
                # If no index property, use arrival order
                msg_index = len(self._buffer)
            
            # Check buffer size limit
            max_size = self.get_config_int('max_buffer_size', 1000)
            if max_size > 0 and len(self._buffer) >= max_size:
                self.report_error(f"Buffer full ({max_size} messages), dropping oldest message")
                # Remove oldest message
                if self._arrival_order:
                    oldest_index = self._arrival_order.pop(0)
                    if oldest_index in self._buffer:
                        del self._buffer[oldest_index]
            
            # Check if duplicate indices are allowed
            allow_duplicates = self.get_config_bool('allow_duplicates', False)
            
            if msg_index in self._buffer:
                if allow_duplicates:
                    # Overwrite with latest message
                    self._buffer[msg_index] = msg
                else:
                    # Keep first message, drop this one
                    # Silently ignore duplicate (already in buffer)
                    return
            else:
                # Store message in buffer (new index)
                self._buffer[msg_index] = msg
                # Track arrival order
                self._arrival_order.append(msg_index)
            
        except Exception as e:
            self.report_error(f"Error buffering message: {str(e)}")
    
    def _release_messages(self, trigger_msg: Dict[str, Any]):
        """
        Release buffered messages according to configuration.
        """
        try:
            if not self._buffer:
                # No messages to release
                output_msg = self.create_message(
                    payload={
                        'status': 'empty',
                        'message': 'No messages in buffer'
                    },
                    topic=trigger_msg.get('topic', 'sync/release')
                )
                self.send(output_msg)
                return
            
            # Get sorted indices
            indices = self._get_sorted_indices()
            
            output_mode = self.config.get('output_mode', 'sequential')
            
            if output_mode == 'sequential':
                # Send messages one by one
                for idx in indices:
                    if idx in self._buffer:
                        self.send(self._buffer[idx])
                
                # Send completion message
                completion_msg = self.create_message(
                    payload={
                        'status': 'complete',
                        'released_count': len(indices),
                        'indices': indices
                    },
                    topic=trigger_msg.get('topic', 'sync/complete')
                )
                self.send(completion_msg)
                
            elif output_mode == 'array':
                # Send all messages as an array
                messages = [self._buffer[idx] for idx in indices if idx in self._buffer]
                
                array_msg = self.create_message(
                    payload={
                        'messages': messages,
                        'count': len(messages),
                        'indices': indices
                    },
                    topic=trigger_msg.get('topic', 'sync/array')
                )
                self.send(array_msg)
            
            # Clear buffer if configured
            if self.get_config_bool('clear_on_release', True):
                self._buffer.clear()
                self._arrival_order.clear()
            
        except Exception as e:
            self.report_error(f"Error releasing messages: {str(e)}")
    
    def _get_sorted_indices(self) -> List[Any]:
        """
        Get list of indices sorted according to configuration.
        """
        sort_order = self.config.get('sort_order', 'ascending')
        
        if sort_order == 'none':
            # Return in arrival order
            return self._arrival_order.copy()
        
        # Get indices and try to sort them
        indices = list(self._buffer.keys())
        
        try:
            if sort_order == 'ascending':
                return sorted(indices)
            elif sort_order == 'descending':
                return sorted(indices, reverse=True)
        except TypeError:
            # If indices can't be compared (mixed types), use arrival order
            return self._arrival_order.copy()
        
        return indices
    
    def get_buffer_status(self) -> Dict[str, Any]:
        """
        Get current buffer status.
        """
        return {
            'buffer_size': len(self._buffer),
            'indices': list(self._buffer.keys()),
            'arrival_order': self._arrival_order.copy()
        }
    
    def clear_buffer(self):
        """
        Manually clear the buffer.
        """
        self._buffer.clear()
        self._arrival_order.clear()
