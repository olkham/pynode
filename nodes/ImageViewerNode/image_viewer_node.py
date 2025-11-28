"""
Image Viewer node - displays images/frames in the web UI.
"""

from typing import Any, Dict
from base_node import BaseNode


class ImageViewerNode(BaseNode):
    """
    Image Viewer node - displays images/frames in the web UI.
    """
    display_name = 'Image Viewer'
    icon = '🖼️'
    category = 'output'
    color = '#D8BFD8'
    border_color = '#9370DB'
    text_color = '#000000'
    input_count = 1
    output_count = 0
    
    properties = [
        {
            'name': 'width',
            'label': 'Display Width (px)',
            'type': 'number',
            'default': 320
        },
        {
            'name': 'height',
            'label': 'Display Height (px)',
            'type': 'number',
            'default': 240
        },
        {
            'name': 'image_path',
            'label': 'Image Data Path',
            'type': 'text',
            'default': 'payload',
            'description': 'Dot-separated path to image data (e.g. payload or payload.image)'
        }
    ]
    
    def __init__(self, node_id=None, name="image viewer"):
        super().__init__(node_id, name)
        self.current_frame = None
        self.frame_timestamp = 0
        self.last_sent_timestamp = 0
        self.configure({
            'width': 320,
            'height': 240,
            'image_path': 'payload'
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Receive image data and store it for display.
        """
        import time
        image_path = self.config.get('image_path', 'payload')

        def get_by_path(obj, path):
            parts = path.split('.')
            for part in parts:
                if isinstance(obj, dict) and part in obj:
                    obj = obj[part]
                else:
                    return None
            return obj

        image_data = get_by_path(msg, image_path)

        if image_data is not None:
            # Store the frame data for the UI to retrieve
            self.current_frame = image_data
            self.frame_timestamp = time.time()
        else:
            # Optionally, raise/log an error if data not found
            if hasattr(self, 'send_error'):
                self.send_error(f"ImageViewerNode: No data found at path '{image_path}' in message.")
            else:
                print(f"ImageViewerNode: No data found at path '{image_path}' in message.")
    
    def on_input_direct(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Direct input processing (bypasses queue for better performance).
        """
        self.on_input(msg, input_index)
    
    def get_current_frame(self):
        """
        Get the current frame for display in the UI.
        Only returns frames that haven't been sent yet.
        """
        if self.current_frame and self.frame_timestamp > self.last_sent_timestamp:
            self.last_sent_timestamp = self.frame_timestamp
            return self.current_frame
        return None
