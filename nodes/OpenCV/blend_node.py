"""
OpenCV Blend Node - blends two images together.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class BlendNode(BaseNode):
    """
    Blend node - blends two images together using weighted addition.
    """
    display_name = 'Blend'
    icon = '⧉'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 2  # Input 0: image1, Input 1: image2
    output_count = 1
    
    DEFAULT_CONFIG = {
        'alpha': 0.5,
        'beta': 0.5,
        'gamma': 0
    }
    
    properties = [
        {
            'name': 'alpha',
            'label': 'Alpha (image 1 weight)',
            'type': 'number',
            'default': DEFAULT_CONFIG['alpha'],
            'min': 0,
            'max': 1,
            'step': 0.1,
            'help': 'Weight for first image (0-1)'
        },
        {
            'name': 'beta',
            'label': 'Beta (image 2 weight)',
            'type': 'number',
            'default': DEFAULT_CONFIG['beta'],
            'min': 0,
            'max': 1,
            'step': 0.1,
            'help': 'Weight for second image (0-1)'
        },
        {
            'name': 'gamma',
            'label': 'Gamma (brightness)',
            'type': 'number',
            'default': DEFAULT_CONFIG['gamma'],
            'min': -100,
            'max': 100,
            'help': 'Added to final result'
        }
    ]
    
    def __init__(self, node_id=None, name="blend"):
        super().__init__(node_id, name)
        self.configure(self.DEFAULT_CONFIG)
        self._image1 = None
        self._image2 = None
        self._format_type = None
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Blend two images."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        if input_index == 0:
            self._image1 = img
            self._format_type = format_type
        else:
            self._image2 = img
        
        # Need both images
        if self._image1 is None or self._image2 is None:
            return
        
        alpha = self.get_config_float('alpha', 0.5)
        beta = self.get_config_float('beta', 0.5)
        gamma = self.get_config_float('gamma', 0)
        
        # Ensure images are same size
        if self._image1.shape[:2] != self._image2.shape[:2]:
            self._image2 = cv2.resize(self._image2, 
                                       (self._image1.shape[1], self._image1.shape[0]))
        
        # Ensure same number of channels
        if len(self._image1.shape) != len(self._image2.shape):
            if len(self._image1.shape) == 2:
                self._image1 = cv2.cvtColor(self._image1, cv2.COLOR_GRAY2BGR)
            if len(self._image2.shape) == 2:
                self._image2 = cv2.cvtColor(self._image2, cv2.COLOR_GRAY2BGR)
        
        result = cv2.addWeighted(self._image1, alpha, self._image2, beta, gamma)
        
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(result, self._format_type)
        self.send(msg)
