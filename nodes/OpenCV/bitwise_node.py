"""
OpenCV Bitwise Operations Node - performs bitwise operations on images.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class BitwiseNode(BaseNode):
    """
    Bitwise node - performs bitwise operations between images or with masks.
    """
    display_name = 'Bitwise'
    icon = '&'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 2  # Input 0: image1, Input 1: image2 or mask
    output_count = 1
    
    DEFAULT_CONFIG = {
        'operation': 'and'
    }
    
    properties = [
        {
            'name': 'operation',
            'label': 'Operation',
            'type': 'select',
            'options': [
                {'value': 'and', 'label': 'AND'},
                {'value': 'or', 'label': 'OR'},
                {'value': 'xor', 'label': 'XOR'},
                {'value': 'not', 'label': 'NOT (invert)'},
                {'value': 'mask', 'label': 'Apply mask'}
            ],
            'default': DEFAULT_CONFIG['operation'],
            'help': 'Bitwise operation to perform'
        }
    ]
    
    def __init__(self, node_id=None, name="bitwise"):
        super().__init__(node_id, name)
        self.configure(self.DEFAULT_CONFIG)
        self._image1 = None
        self._image2 = None
        self._format_type = None
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Perform bitwise operation."""
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
        
        operation = self.config.get('operation', 'and')
        
        # NOT operation only needs one image
        if operation == 'not' and self._image1 is not None:
            result = cv2.bitwise_not(self._image1)
            if 'payload' not in msg or not isinstance(msg['payload'], dict):
                msg['payload'] = {}
            msg['payload']['image'] = self.encode_image(result, self._format_type)
            self.send(msg)
            return
        
        # Other operations need both images
        if self._image1 is None or self._image2 is None:
            return
        
        # Ensure images are same size
        if self._image1.shape[:2] != self._image2.shape[:2]:
            # Resize image2 to match image1
            self._image2 = cv2.resize(self._image2, 
                                       (self._image1.shape[1], self._image1.shape[0]))
        
        if operation == 'and':
            result = cv2.bitwise_and(self._image1, self._image2)
        elif operation == 'or':
            result = cv2.bitwise_or(self._image1, self._image2)
        elif operation == 'xor':
            result = cv2.bitwise_xor(self._image1, self._image2)
        elif operation == 'mask':
            # Use image2 as mask
            if len(self._image2.shape) == 3:
                mask = cv2.cvtColor(self._image2, cv2.COLOR_BGR2GRAY)
            else:
                mask = self._image2
            result = cv2.bitwise_and(self._image1, self._image1, mask=mask)
        else:
            result = self._image1
        
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(result, self._format_type)
        self.send(msg)
