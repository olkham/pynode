"""
OpenCV Threshold Node - applies thresholding to images.
Converts grayscale images to binary using various thresholding methods.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class ThresholdNode(BaseNode):
    """
    Threshold node - applies thresholding to grayscale images.
    Supports binary, binary inverted, truncate, to-zero, and adaptive methods.
    """
    display_name = 'Threshold'
    icon = '◐'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'method',
            'label': 'Method',
            'type': 'select',
            'options': [
                {'value': 'binary', 'label': 'Binary'},
                {'value': 'binary_inv', 'label': 'Binary Inverted'},
                {'value': 'trunc', 'label': 'Truncate'},
                {'value': 'tozero', 'label': 'To Zero'},
                {'value': 'tozero_inv', 'label': 'To Zero Inverted'},
                {'value': 'otsu', 'label': 'Otsu (auto)'},
                {'value': 'adaptive_mean', 'label': 'Adaptive Mean'},
                {'value': 'adaptive_gaussian', 'label': 'Adaptive Gaussian'}
            ],
            'default': 'binary',
            'help': 'Thresholding method to apply'
        },
        {
            'name': 'threshold',
            'label': 'Threshold Value',
            'type': 'number',
            'default': 127,
            'min': 0,
            'max': 255,
            'help': 'Threshold value (ignored for Otsu and adaptive methods)',
            'showIf': {'method': ['binary', 'binary_inv', 'trunc', 'tozero', 'tozero_inv']}
        },
        {
            'name': 'max_value',
            'label': 'Max Value',
            'type': 'number',
            'default': 255,
            'min': 0,
            'max': 255,
            'help': 'Maximum value for binary thresholding'
        },
        {
            'name': 'block_size',
            'label': 'Block Size',
            'type': 'number',
            'default': 11,
            'min': 3,
            'max': 99,
            'help': 'Block size for adaptive methods (must be odd)',
            'showIf': {'method': ['adaptive_mean', 'adaptive_gaussian']}
        },
        {
            'name': 'c_value',
            'label': 'C Value',
            'type': 'number',
            'default': 2,
            'help': 'Constant subtracted from mean (adaptive methods)',
            'showIf': {'method': ['adaptive_mean', 'adaptive_gaussian']}
        },
        {
            'name': 'convert_gray',
            'label': 'Auto Convert to Grayscale',
            'type': 'select',
            'options': [
                {'value': 'yes', 'label': 'Yes'},
                {'value': 'no', 'label': 'No'}
            ],
            'default': 'yes',
            'help': 'Automatically convert color images to grayscale'
        }
    ]
    
    def __init__(self, node_id=None, name="threshold"):
        super().__init__(node_id, name)
        self.configure({
            'method': 'binary',
            'threshold': 127,
            'max_value': 255,
            'block_size': 11,
            'c_value': 2,
            'convert_gray': 'yes'
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Apply thresholding to the input image."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        # Decode image from any supported format
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        method = self.config.get('method', 'binary')
        thresh_val = int(self.config.get('threshold', 127))
        max_val = int(self.config.get('max_value', 255))
        block_size = int(self.config.get('block_size', 11))
        c_value = int(self.config.get('c_value', 2))
        convert_gray = self.config.get('convert_gray', 'yes') == 'yes'
        
        # Ensure block_size is odd
        if block_size % 2 == 0:
            block_size += 1
        
        # Convert to grayscale if needed
        if len(img.shape) == 3 and convert_gray:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        elif len(img.shape) == 2:
            gray = img
        else:
            # Can't process, pass through
            self.send(msg)
            return
        
        # Apply thresholding based on method
        if method == 'binary':
            _, result = cv2.threshold(gray, thresh_val, max_val, cv2.THRESH_BINARY)
        elif method == 'binary_inv':
            _, result = cv2.threshold(gray, thresh_val, max_val, cv2.THRESH_BINARY_INV)
        elif method == 'trunc':
            _, result = cv2.threshold(gray, thresh_val, max_val, cv2.THRESH_TRUNC)
        elif method == 'tozero':
            _, result = cv2.threshold(gray, thresh_val, max_val, cv2.THRESH_TOZERO)
        elif method == 'tozero_inv':
            _, result = cv2.threshold(gray, thresh_val, max_val, cv2.THRESH_TOZERO_INV)
        elif method == 'otsu':
            _, result = cv2.threshold(gray, 0, max_val, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        elif method == 'adaptive_mean':
            result = cv2.adaptiveThreshold(gray, max_val, cv2.ADAPTIVE_THRESH_MEAN_C,
                                           cv2.THRESH_BINARY, block_size, c_value)
        elif method == 'adaptive_gaussian':
            result = cv2.adaptiveThreshold(gray, max_val, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                           cv2.THRESH_BINARY, block_size, c_value)
        else:
            result = gray
        
        # Convert grayscale result to BGR for encoding
        result_bgr = cv2.cvtColor(result, cv2.COLOR_GRAY2BGR)
        
        # Encode back to original format
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(result, format_type)
        self.send(msg)
