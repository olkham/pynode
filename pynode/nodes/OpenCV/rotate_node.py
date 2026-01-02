"""
OpenCV Rotate Node - rotates images.
"""

import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, process_image, Info

_info = Info()
_info.add_text("Rotates and flips images. Supports preset rotations (90°, 180°), custom angles, and flip operations.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Source image"))
_info.add_header("Outputs")
_info.add_bullets(("Output 0:", "Rotated/flipped image"))
_info.add_header("Modes")
_info.add_bullets(
    ("90° CW/CCW:", "Fast 90-degree rotations"),
    ("180°:", "Rotate upside down"),
    ("Custom Angle:", "Rotate by any angle in degrees"),
    ("Flip H/V/Both:", "Mirror image horizontally, vertically, or both")
)
_info.add_header("Custom Angle Options")
_info.add_bullets(
    ("Expand Canvas:", "Grow canvas to fit rotated image"),
    ("Fill Color:", "Color for empty areas (B,G,R format)")
)

class RotateNode(BaseNode):
    """
    Rotate node - rotates images by specified angle.
    """
    info = str(_info)
    display_name = 'Rotate'
    icon = '↻'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'mode': '90cw',
        'angle': 45,
        'expand': 'yes',
        'fill_color': '0,0,0'
    }
    
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
            'default': DEFAULT_CONFIG['mode'],
            'help': 'Rotation mode'
        },
        {
            'name': 'angle',
            'label': 'Angle (degrees)',
            'type': 'number',
            'default': DEFAULT_CONFIG['angle'],
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
            'default': DEFAULT_CONFIG['expand'],
            'help': 'Expand canvas to fit rotated image',
            'showIf': {'mode': 'angle'}
        },
        {
            'name': 'fill_color',
            'label': 'Fill Color (B,G,R)',
            'type': 'text',
            'default': DEFAULT_CONFIG['fill_color'],
            'help': 'Color to fill empty areas',
            'showIf': {'mode': 'angle'}
        }
    ]
    
    def __init__(self, node_id=None, name="rotate"):
        super().__init__(node_id, name)
    
    def _parse_color(self, color_str):
        """Parse color string to BGR tuple."""
        try:
            parts = [int(x.strip()) for x in str(color_str).split(',')]
            if len(parts) >= 3:
                return (parts[0], parts[1], parts[2])
            return (0, 0, 0)
        except:
            return (0, 0, 0)
    
    @process_image()
    def on_input(self, image: np.ndarray, msg: Dict[str, Any], input_index: int = 0):
        """Rotate the input image."""
        mode = self.config.get('mode', '90cw')
        
        if mode == '90cw':
            result = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        elif mode == '90ccw':
            result = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif mode == '180':
            result = cv2.rotate(image, cv2.ROTATE_180)
        elif mode == 'flip_h':
            result = cv2.flip(image, 1)
        elif mode == 'flip_v':
            result = cv2.flip(image, 0)
        elif mode == 'flip_both':
            result = cv2.flip(image, -1)
        elif mode == 'angle':
            angle = self.get_config_float('angle', 45)
            expand = self.get_config_bool('expand', True)
            fill_color = self._parse_color(self.config.get('fill_color', '0,0,0'))
            
            h, w = image.shape[:2]
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
                
                result = cv2.warpAffine(image, M, (new_w, new_h), 
                                        borderValue=fill_color)
            else:
                result = cv2.warpAffine(image, M, (w, h), 
                                        borderValue=fill_color)
        else:
            result = image
        
        return result
