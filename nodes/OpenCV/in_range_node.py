"""
OpenCV In Range Node - filters image pixels by color/intensity range.
Useful for color-based object detection and masking.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class InRangeNode(BaseNode):
    """
    In Range node - creates a binary mask from pixels within a color range.
    Works with any color space (HSV recommended for color filtering).
    """
    display_name = 'In Range'
    icon = '🎯'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 2  # Output 0: mask, Output 1: masked image
    
    DEFAULT_CONFIG = {
        'channel1_min': 0,
        'channel1_max': 180,
        'channel2_min': 50,
        'channel2_max': 255,
        'channel3_min': 50,
        'channel3_max': 255,
        'output_mode': 'both'
    }
    
    properties = [
        {
            'name': 'channel1_min',
            'label': 'Channel 1 Min (H/B)',
            'type': 'number',
            'default': DEFAULT_CONFIG['channel1_min'],
            'min': 0,
            'max': 255,
            'help': 'Minimum value for channel 1 (Hue in HSV: 0-179)'
        },
        {
            'name': 'channel1_max',
            'label': 'Channel 1 Max (H/B)',
            'type': 'number',
            'default': DEFAULT_CONFIG['channel1_max'],
            'min': 0,
            'max': 255,
            'help': 'Maximum value for channel 1'
        },
        {
            'name': 'channel2_min',
            'label': 'Channel 2 Min (S/G)',
            'type': 'number',
            'default': DEFAULT_CONFIG['channel2_min'],
            'min': 0,
            'max': 255,
            'help': 'Minimum value for channel 2 (Saturation in HSV)'
        },
        {
            'name': 'channel2_max',
            'label': 'Channel 2 Max (S/G)',
            'type': 'number',
            'default': DEFAULT_CONFIG['channel2_max'],
            'min': 0,
            'max': 255,
            'help': 'Maximum value for channel 2'
        },
        {
            'name': 'channel3_min',
            'label': 'Channel 3 Min (V/R)',
            'type': 'number',
            'default': DEFAULT_CONFIG['channel3_min'],
            'min': 0,
            'max': 255,
            'help': 'Minimum value for channel 3 (Value in HSV)'
        },
        {
            'name': 'channel3_max',
            'label': 'Channel 3 Max (V/R)',
            'type': 'number',
            'default': DEFAULT_CONFIG['channel3_max'],
            'min': 0,
            'max': 255,
            'help': 'Maximum value for channel 3'
        },
        {
            'name': 'output_mode',
            'label': 'Output Mode',
            'type': 'select',
            'options': [
                {'value': 'mask', 'label': 'Mask only'},
                {'value': 'masked', 'label': 'Masked image only'},
                {'value': 'both', 'label': 'Both (mask + masked)'}
            ],
            'default': DEFAULT_CONFIG['output_mode'],
            'help': 'What to include in output'
        }
    ]
    
    def __init__(self, node_id=None, name="in range"):
        super().__init__(node_id, name)
        self.configure(self.DEFAULT_CONFIG)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Apply color range filter to the input image."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        # Get range values
        lower = np.array([
            int(self.config.get('channel1_min', 0)),
            int(self.config.get('channel2_min', 0)),
            int(self.config.get('channel3_min', 0))
        ])
        upper = np.array([
            int(self.config.get('channel1_max', 255)),
            int(self.config.get('channel2_max', 255)),
            int(self.config.get('channel3_max', 255))
        ])
        
        output_mode = self.config.get('output_mode', 'both')
        
        # Handle grayscale images
        if len(img.shape) == 2:
            mask = cv2.inRange(img, lower[0], upper[0])
        else:
            mask = cv2.inRange(img, lower, upper)
        
        # Apply mask to get masked image
        if len(img.shape) == 2:
            masked = cv2.bitwise_and(img, img, mask=mask)
        else:
            masked = cv2.bitwise_and(img, img, mask=mask)
        
        # Count non-zero pixels
        pixel_count = cv2.countNonZero(mask)
        total_pixels = mask.shape[0] * mask.shape[1]
        coverage = pixel_count / total_pixels if total_pixels > 0 else 0
        
        msg['mask_pixels'] = pixel_count
        msg['mask_coverage'] = coverage
        
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        
        if output_mode == 'mask':
            msg['payload']['image'] = self.encode_image(mask, format_type)
            self.send(msg, 0)
        elif output_mode == 'masked':
            msg['payload']['image'] = self.encode_image(masked, format_type)
            self.send(msg, 0)
        else:  # both
            msg['payload']['image'] = self.encode_image(mask, format_type)
            msg['payload']['masked_image'] = self.encode_image(masked, format_type)
            self.send(msg, 0)
            
            msg2 = msg.copy()
            msg2['payload'] = {'image': self.encode_image(masked, format_type)}
            self.send(msg2, 1)
