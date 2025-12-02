"""
Image Viewer node - displays images/frames in the web UI.
"""

import base64
import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


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
            'default': 'payload.image',
            'description': 'Dot-separated path to image data (e.g. payload.image)'
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
            'image_path': 'payload.image'
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
            # Decode image using base node helper
            img, format_type = self.decode_image({'image': image_data})
            
            if img is None:
                self.report_error(f"ImageViewerNode: Failed to decode image")
                return
            
            # Always encode to base64 JPEG for browser display
            encoded_image = self.encode_image(img, 'jpeg_base64_dict')
            if encoded_image is None:
                self.report_error(f"ImageViewerNode: Failed to encode image for display")
                return
            
            # Store the frame data for the UI to retrieve
            self.current_frame = encoded_image
            self.frame_timestamp = time.time()
        else:
            self.report_error(f"ImageViewerNode: No data found at path '{image_path}' in message.")
    
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
