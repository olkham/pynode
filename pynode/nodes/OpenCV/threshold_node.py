"""
OpenCV Threshold Node - applies thresholding to images.
Converts grayscale images to binary using various thresholding methods.
"""

import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, process_image, Info

_info = Info()
_info.add_text("Converts grayscale images to binary using various thresholding methods. Essential for image segmentation and preparing images for contour detection.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Grayscale image (auto-converts color if enabled)"))
_info.add_header("Outputs")
_info.add_bullets(("Output 0:", "Binary/thresholded image"))
_info.add_header("Methods")
_info.add_bullets(
    ("Binary:", "Pixels above threshold become white, others black"),
    ("Binary Inv:", "Inverse of binary"),
    ("Truncate:", "Cap values at threshold"),
    ("To Zero:", "Below threshold becomes 0"),
    ("Otsu:", "Automatic threshold calculation"),
    ("Adaptive Mean/Gaussian:", "Local threshold based on neighborhood")
)

class ThresholdNode(BaseNode):
    """
    Threshold node - applies thresholding to grayscale images.
    Supports binary, binary inverted, truncate, to-zero, and adaptive methods.
    """
    info = str(_info)
    display_name = 'Threshold'
    icon = '◐'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'method': 'binary',
        'threshold': 127,
        'max_value': 255,
        'block_size': 11,
        'c_value': 2,
        'convert_gray': 'yes'
    }
    
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
            'default': DEFAULT_CONFIG['method'],
            'help': 'Thresholding method to apply'
        },
        {
            'name': 'threshold',
            'label': 'Threshold Value',
            'type': 'number',
            'default': DEFAULT_CONFIG['threshold'],
            'min': 0,
            'max': 255,
            'help': 'Threshold value (ignored for Otsu and adaptive methods)',
            'showIf': {'method': ['binary', 'binary_inv', 'trunc', 'tozero', 'tozero_inv']}
        },
        {
            'name': 'max_value',
            'label': 'Max Value',
            'type': 'number',
            'default': DEFAULT_CONFIG['max_value'],
            'min': 0,
            'max': 255,
            'help': 'Maximum value for binary thresholding'
        },
        {
            'name': 'block_size',
            'label': 'Block Size',
            'type': 'number',
            'default': DEFAULT_CONFIG['block_size'],
            'min': 3,
            'max': 99,
            'help': 'Block size for adaptive methods (must be odd)',
            'showIf': {'method': ['adaptive_mean', 'adaptive_gaussian']}
        },
        {
            'name': 'c_value',
            'label': 'C Value',
            'type': 'number',
            'default': DEFAULT_CONFIG['c_value'],
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
            'default': DEFAULT_CONFIG['convert_gray'],
            'help': 'Automatically convert color images to grayscale'
        }
    ]
    
    def __init__(self, node_id=None, name="threshold"):
        super().__init__(node_id, name)
    
    @process_image()
    def on_input(self, image: np.ndarray, msg: Dict[str, Any], input_index: int = 0):
        """Apply thresholding to the input image."""
        method = self.config.get('method', 'binary')
        thresh_val = self.get_config_int('threshold', 127)
        max_val = self.get_config_int('max_value', 255)
        block_size = self.get_config_int('block_size', 11)
        c_value = self.get_config_int('c_value', 2)
        convert_gray = self.get_config_bool('convert_gray', True)
        
        # Ensure block_size is odd
        if block_size % 2 == 0:
            block_size += 1
        
        # Convert to grayscale if needed
        if len(image.shape) == 3 and convert_gray:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif len(image.shape) == 2:
            gray = image
        else:
            # Can't process, pass through
            return image
        
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
        
        return result
