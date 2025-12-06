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
    
    DEFAULT_CONFIG = {
        'method': 'gaussian',
        'kernel_size': 5,
        'sigma': 0,
        'sigma_color': 75,
        'sigma_space': 75
    }
    
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
            'default': DEFAULT_CONFIG['method'],
            'help': 'Blur method to apply'
        },
        {
            'name': 'kernel_size',
            'label': 'Kernel Size',
            'type': 'number',
            'default': DEFAULT_CONFIG['kernel_size'],
            'min': 1,
            'max': 99,
            'help': 'Size of blur kernel (must be odd for most methods)'
        },
        {
            'name': 'sigma',
            'label': 'Sigma',
            'type': 'number',
            'default': DEFAULT_CONFIG['sigma'],
            'min': 0,
            'help': 'Gaussian sigma (0 = auto calculate from kernel size)',
            'showIf': {'method': 'gaussian'}
        },
        {
            'name': 'sigma_color',
            'label': 'Sigma Color',
            'type': 'number',
            'default': DEFAULT_CONFIG['sigma_color'],
            'min': 1,
            'help': 'Bilateral filter sigma in color space',
            'showIf': {'method': 'bilateral'}
        },
        {
            'name': 'sigma_space',
            'label': 'Sigma Space',
            'type': 'number',
            'default': DEFAULT_CONFIG['sigma_space'],
            'min': 1,
            'help': 'Bilateral filter sigma in coordinate space',
            'showIf': {'method': 'bilateral'}
        }
    ]
    
    def __init__(self, node_id=None, name="blur"):
        super().__init__(node_id, name)
        self.configure(self.DEFAULT_CONFIG)
    
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
        
        # Preserve bbox if present (for crop workflows)
        bbox = None
        if isinstance(msg.get('payload'), dict):
            bbox = msg['payload'].get('bbox')
        
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(result, format_type)
        
        # Restore bbox if it was present
        if bbox is not None:
            msg['payload']['bbox'] = bbox
            # Also set at message level for PasteNode
            msg['bbox'] = {'x1': bbox[0], 'y1': bbox[1], 'x2': bbox[2], 'y2': bbox[3]}
        
        self.send(msg)
