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
        }
    ]
    
    def __init__(self, node_id=None, name="image viewer"):
        super().__init__(node_id, name)
        self.current_frame = None
        self.frame_timestamp = 0
        self.last_sent_timestamp = 0
        self.configure({
            'width': 320,
            'height': 240
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Receive image data and store it for display.
        """
        import time
        payload = msg.get('payload')
        
        if payload and isinstance(payload, dict):
            # Store the frame data for the UI to retrieve
            self.current_frame = payload
            self.frame_timestamp = time.time()
    
    def get_current_frame(self):
        """
        Get the current frame for display in the UI.
        Only returns frames that haven't been sent yet.
        """
        if self.current_frame and self.frame_timestamp > self.last_sent_timestamp:
            self.last_sent_timestamp = self.frame_timestamp
            return self.current_frame
        return None
