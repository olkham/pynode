"""
OpenCV Blur Node - applies various blur/smoothing filters to images.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class BlurNode(BaseNode):
    """
    Blur node - applies smoothing/blur filters to images.
    Supports Gaussian, median, bilateral, and box blur.
    """
    display_name = 'Blur'
    icon = '◌'
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
                {'value': 'gaussian', 'label': 'Gaussian'},
                {'value': 'median', 'label': 'Median'},
                {'value': 'bilateral', 'label': 'Bilateral'},
                {'value': 'box', 'label': 'Box (average)'},
                {'value': 'stack', 'label': 'Stack Blur'}
            ],
            'default': 'gaussian',
            'help': 'Blur method to apply'
        },
        {
            'name': 'kernel_size',
            'label': 'Kernel Size',
            'type': 'number',
            'default': 5,
            'min': 1,
            'max': 99,
            'help': 'Size of blur kernel (must be odd for most methods)'
        },
        {
            'name': 'sigma',
            'label': 'Sigma',
            'type': 'number',
            'default': 0,
            'min': 0,
            'help': 'Gaussian sigma (0 = auto calculate from kernel size)'
        },
        {
            'name': 'sigma_color',
            'label': 'Sigma Color',
            'type': 'number',
            'default': 75,
            'min': 1,
            'help': 'Bilateral filter sigma in color space'
        },
        {
            'name': 'sigma_space',
            'label': 'Sigma Space',
            'type': 'number',
            'default': 75,
            'min': 1,
            'help': 'Bilateral filter sigma in coordinate space'
        }
    ]
    
    def __init__(self, node_id=None, name="blur"):
        super().__init__(node_id, name)
        self.configure({
            'method': 'gaussian',
            'kernel_size': 5,
            'sigma': 0,
            'sigma_color': 75,
            'sigma_space': 75
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Apply blur to the input image."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        method = self.config.get('method', 'gaussian')
        ksize = int(self.config.get('kernel_size', 5))
        sigma = float(self.config.get('sigma', 0))
        sigma_color = float(self.config.get('sigma_color', 75))
        sigma_space = float(self.config.get('sigma_space', 75))
        
        # Ensure kernel size is odd for methods that require it
        if ksize % 2 == 0:
            ksize += 1
        
        if method == 'gaussian':
            result = cv2.GaussianBlur(img, (ksize, ksize), sigma)
        elif method == 'median':
            result = cv2.medianBlur(img, ksize)
        elif method == 'bilateral':
            result = cv2.bilateralFilter(img, ksize, sigma_color, sigma_space)
        elif method == 'box':
            result = cv2.blur(img, (ksize, ksize))
        elif method == 'stack':
            result = cv2.stackBlur(img, (ksize, ksize))
        else:
            result = img
        
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(result, format_type)
        self.send(msg)
