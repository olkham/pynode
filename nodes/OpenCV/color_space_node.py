"""
OpenCV Color Space Converter Node - converts between color spaces.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class ColorSpaceNode(BaseNode):
    """
    Color Space node - converts images between different color spaces.
    Supports BGR, RGB, HSV, HLS, LAB, YUV, and grayscale.
    """
    display_name = 'Color Space'
    icon = '🎨'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'input_space': 'bgr',
        'output_space': 'gray'
    }
    
    properties = [
        {
            'name': 'input_space',
            'label': 'Input Color Space',
            'type': 'select',
            'options': [
                {'value': 'bgr', 'label': 'BGR'},
                {'value': 'rgb', 'label': 'RGB'},
                {'value': 'hsv', 'label': 'HSV'},
                {'value': 'hls', 'label': 'HLS'},
                {'value': 'lab', 'label': 'LAB'},
                {'value': 'yuv', 'label': 'YUV'},
                {'value': 'gray', 'label': 'Grayscale'}
            ],
            'default': DEFAULT_CONFIG['input_space'],
            'help': 'Input image color space'
        },
        {
            'name': 'output_space',
            'label': 'Output Color Space',
            'type': 'select',
            'options': [
                {'value': 'bgr', 'label': 'BGR'},
                {'value': 'rgb', 'label': 'RGB'},
                {'value': 'hsv', 'label': 'HSV'},
                {'value': 'hls', 'label': 'HLS'},
                {'value': 'lab', 'label': 'LAB'},
                {'value': 'yuv', 'label': 'YUV'},
                {'value': 'gray', 'label': 'Grayscale'}
            ],
            'default': DEFAULT_CONFIG['output_space'],
            'help': 'Output image color space'
        }
    ]
    
    def __init__(self, node_id=None, name="color space"):
        super().__init__(node_id, name)
        self.configure(self.DEFAULT_CONFIG)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Convert image color space."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        input_space = self.config.get('input_space', 'bgr')
        output_space = self.config.get('output_space', 'gray')
        
        # No conversion needed if same
        if input_space == output_space:
            self.send(msg)
            return
        
        # Define conversion codes
        conversions = {
            ('bgr', 'rgb'): cv2.COLOR_BGR2RGB,
            ('bgr', 'gray'): cv2.COLOR_BGR2GRAY,
            ('bgr', 'hsv'): cv2.COLOR_BGR2HSV,
            ('bgr', 'hls'): cv2.COLOR_BGR2HLS,
            ('bgr', 'lab'): cv2.COLOR_BGR2LAB,
            ('bgr', 'yuv'): cv2.COLOR_BGR2YUV,
            ('rgb', 'bgr'): cv2.COLOR_RGB2BGR,
            ('rgb', 'gray'): cv2.COLOR_RGB2GRAY,
            ('rgb', 'hsv'): cv2.COLOR_RGB2HSV,
            ('rgb', 'hls'): cv2.COLOR_RGB2HLS,
            ('rgb', 'lab'): cv2.COLOR_RGB2LAB,
            ('rgb', 'yuv'): cv2.COLOR_RGB2YUV,
            ('hsv', 'bgr'): cv2.COLOR_HSV2BGR,
            ('hsv', 'rgb'): cv2.COLOR_HSV2RGB,
            ('hls', 'bgr'): cv2.COLOR_HLS2BGR,
            ('hls', 'rgb'): cv2.COLOR_HLS2RGB,
            ('lab', 'bgr'): cv2.COLOR_LAB2BGR,
            ('lab', 'rgb'): cv2.COLOR_LAB2RGB,
            ('yuv', 'bgr'): cv2.COLOR_YUV2BGR,
            ('yuv', 'rgb'): cv2.COLOR_YUV2RGB,
            ('gray', 'bgr'): cv2.COLOR_GRAY2BGR,
            ('gray', 'rgb'): cv2.COLOR_GRAY2RGB,
        }
        
        conversion_key = (input_space, output_space)
        
        if conversion_key in conversions:
            result = cv2.cvtColor(img, conversions[conversion_key])
        else:
            # Try two-step conversion via BGR
            if input_space != 'bgr' and (input_space, 'bgr') in conversions:
                temp = cv2.cvtColor(img, conversions[(input_space, 'bgr')])
                if ('bgr', output_space) in conversions:
                    result = cv2.cvtColor(temp, conversions[('bgr', output_space)])
                else:
                    result = temp
            else:
                result = img
        
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(result, format_type)
        self.send(msg)
