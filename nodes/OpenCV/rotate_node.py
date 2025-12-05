"""
OpenCV Rotate Node - rotates images.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class RotateNode(BaseNode):
    """
    Rotate node - rotates images by specified angle.
    """
    display_name = 'Rotate'
    icon = '↻'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'mode',
            'label': 'Mode',
            'type': 'select',
            'options': [
                {'value': 'angle', 'label': 'Custom angle'},
                {'value': '90cw', 'label': '90° clockwise'},
                {'value': '90ccw', 'label': '90° counter-clockwise'},
                {'value': '180', 'label': '180°'},
                {'value': 'flip_h', 'label': 'Flip horizontal'},
                {'value': 'flip_v', 'label': 'Flip vertical'},
                {'value': 'flip_both', 'label': 'Flip both'}
            ],
            'default': '90cw',
            'help': 'Rotation mode'
        },
        {
            'name': 'angle',
            'label': 'Angle (degrees)',
            'type': 'number',
            'default': 45,
            'min': -360,
            'max': 360,
            'help': 'Rotation angle in degrees (positive = counter-clockwise)',
            'showIf': {'mode': 'angle'}
        },
        {
            'name': 'expand',
            'label': 'Expand Canvas',
            'type': 'select',
            'options': [
                {'value': 'yes', 'label': 'Yes'},
                {'value': 'no', 'label': 'No'}
            ],
            'default': 'yes',
            'help': 'Expand canvas to fit rotated image',
            'showIf': {'mode': 'angle'}
        },
        {
            'name': 'fill_color',
            'label': 'Fill Color (B,G,R)',
            'type': 'text',
            'default': '0,0,0',
            'help': 'Color to fill empty areas',
            'showIf': {'mode': 'angle'}
        }
    ]
    
    def __init__(self, node_id=None, name="rotate"):
        super().__init__(node_id, name)
        self.configure({
            'mode': '90cw',
            'angle': 45,
            'expand': 'yes',
            'fill_color': '0,0,0'
        })
    
    def _parse_color(self, color_str):
        """Parse color string to BGR tuple."""
        try:
            parts = [int(x.strip()) for x in str(color_str).split(',')]
            if len(parts) >= 3:
                return (parts[0], parts[1], parts[2])
            return (0, 0, 0)
        except:
            return (0, 0, 0)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Rotate the input image."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        mode = self.config.get('mode', '90cw')
        
        if mode == '90cw':
            result = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif mode == '90ccw':
            result = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif mode == '180':
            result = cv2.rotate(img, cv2.ROTATE_180)
        elif mode == 'flip_h':
            result = cv2.flip(img, 1)
        elif mode == 'flip_v':
            result = cv2.flip(img, 0)
        elif mode == 'flip_both':
            result = cv2.flip(img, -1)
        elif mode == 'angle':
            angle = float(self.config.get('angle', 45))
            expand = self.config.get('expand', 'yes') == 'yes'
            fill_color = self._parse_color(self.config.get('fill_color', '0,0,0'))
            
            h, w = img.shape[:2]
            center = (w // 2, h // 2)
            
            # Get rotation matrix
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            
            if expand:
                # Calculate new bounding box size
                cos = np.abs(M[0, 0])
                sin = np.abs(M[0, 1])
                new_w = int(h * sin + w * cos)
                new_h = int(h * cos + w * sin)
                
                # Adjust the rotation matrix
                M[0, 2] += (new_w - w) / 2
                M[1, 2] += (new_h - h) / 2
                
                result = cv2.warpAffine(img, M, (new_w, new_h), 
                                        borderValue=fill_color)
            else:
                result = cv2.warpAffine(img, M, (w, h), 
                                        borderValue=fill_color)
        else:
            result = img
        
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(result, format_type)
        self.send(msg)
