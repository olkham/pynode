"""
OpenCV Histogram Node - computes and optionally equalizes image histograms.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class HistogramNode(BaseNode):
    """
    Histogram node - computes histograms and applies histogram equalization.
    """
    display_name = 'Histogram'
    icon = '📊'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'operation',
            'label': 'Operation',
            'type': 'select',
            'options': [
                {'value': 'compute', 'label': 'Compute histogram only'},
                {'value': 'equalize', 'label': 'Histogram equalization'},
                {'value': 'clahe', 'label': 'CLAHE (adaptive)'},
                {'value': 'normalize', 'label': 'Normalize'}
            ],
            'default': 'equalize',
            'help': 'Histogram operation to perform'
        },
        {
            'name': 'clip_limit',
            'label': 'CLAHE Clip Limit',
            'type': 'number',
            'default': 2.0,
            'min': 0.1,
            'max': 10,
            'step': 0.1,
            'help': 'Threshold for contrast limiting (CLAHE)'
        },
        {
            'name': 'tile_size',
            'label': 'CLAHE Tile Size',
            'type': 'number',
            'default': 8,
            'min': 2,
            'max': 32,
            'help': 'Size of grid for CLAHE'
        },
        {
            'name': 'normalize_alpha',
            'label': 'Normalize Alpha',
            'type': 'number',
            'default': 0,
            'min': 0,
            'max': 255,
            'help': 'Lower bound for normalization'
        },
        {
            'name': 'normalize_beta',
            'label': 'Normalize Beta',
            'type': 'number',
            'default': 255,
            'min': 0,
            'max': 255,
            'help': 'Upper bound for normalization'
        }
    ]
    
    def __init__(self, node_id=None, name="histogram"):
        super().__init__(node_id, name)
        self.configure({
            'operation': 'equalize',
            'clip_limit': 2.0,
            'tile_size': 8,
            'normalize_alpha': 0,
            'normalize_beta': 255
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Process image histogram."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        operation = self.config.get('operation', 'equalize')
        clip_limit = float(self.config.get('clip_limit', 2.0))
        tile_size = int(self.config.get('tile_size', 8))
        alpha = int(self.config.get('normalize_alpha', 0))
        beta = int(self.config.get('normalize_beta', 255))
        
        # Convert to grayscale for processing if color
        if len(img.shape) == 3:
            is_color = True
            # Convert to LAB for better color handling
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l_channel = lab[:, :, 0]
        else:
            is_color = False
            l_channel = img
        
        # Compute histogram
        hist = cv2.calcHist([l_channel], [0], None, [256], [0, 256])
        msg['histogram'] = hist.flatten().tolist()
        
        if operation == 'compute':
            # Just compute, don't modify image
            self.send(msg)
            return
        
        if operation == 'equalize':
            result = cv2.equalizeHist(l_channel)
        elif operation == 'clahe':
            clahe = cv2.createCLAHE(clipLimit=clip_limit, 
                                    tileGridSize=(tile_size, tile_size))
            result = clahe.apply(l_channel)
        elif operation == 'normalize':
            result = cv2.normalize(l_channel, None, alpha, beta, cv2.NORM_MINMAX)
        else:
            result = l_channel
        
        # Reconstruct color image if needed
        if is_color:
            lab[:, :, 0] = result
            output = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        else:
            output = result
        
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(output, format_type)
        self.send(msg)
