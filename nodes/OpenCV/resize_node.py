"""
OpenCV Resize Node - resizes images.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode, process_image


class ResizeNode(BaseNode):
    """
    Resize node - resizes images to specified dimensions or scale.
    """
    display_name = 'Resize'
    icon = '⤡'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'mode': 'scale',
        'width': 640,
        'height': 480,
        'scale': 0.5,
        'interpolation': 'linear'
    }
    
    properties = [
        {
            'name': 'mode',
            'label': 'Mode',
            'type': 'select',
            'options': [
                {'value': 'absolute', 'label': 'Absolute size'},
                {'value': 'scale', 'label': 'Scale factor'},
                {'value': 'fit', 'label': 'Fit within bounds'},
                {'value': 'fill', 'label': 'Fill bounds (crop)'}
            ],
            'default': DEFAULT_CONFIG['mode'],
            'help': 'How to determine new size'
        },
        {
            'name': 'width',
            'label': 'Width',
            'type': 'number',
            'default': DEFAULT_CONFIG['width'],
            'min': 1,
            'help': 'Target width in pixels',
            'showIf': {'mode': ['absolute', 'fit', 'fill']}
        },
        {
            'name': 'height',
            'label': 'Height',
            'type': 'number',
            'default': DEFAULT_CONFIG['height'],
            'min': 1,
            'help': 'Target height in pixels',
            'showIf': {'mode': ['absolute', 'fit', 'fill']}
        },
        {
            'name': 'scale',
            'label': 'Scale Factor',
            'type': 'number',
            'default': DEFAULT_CONFIG['scale'],
            'min': 0.01,
            'max': 10,
            'step': 0.1,
            'help': 'Scale multiplier (1.0 = original size)',
            'showIf': {'mode': 'scale'}
        },
        {
            'name': 'interpolation',
            'label': 'Interpolation',
            'type': 'select',
            'options': [
                {'value': 'nearest', 'label': 'Nearest neighbor'},
                {'value': 'linear', 'label': 'Bilinear'},
                {'value': 'area', 'label': 'Area (best for shrinking)'},
                {'value': 'cubic', 'label': 'Bicubic'},
                {'value': 'lanczos', 'label': 'Lanczos'}
            ],
            'default': DEFAULT_CONFIG['interpolation'],
            'help': 'Interpolation method'
        }
    ]
    
    def __init__(self, node_id=None, name="resize"):
        super().__init__(node_id, name)
    
    @process_image()
    def on_input(self, image: np.ndarray, msg: Dict[str, Any], input_index: int = 0):
        """Resize the input image."""
        mode = self.config.get('mode', 'scale')
        target_width = self.get_config_int('width', 640)
        target_height = self.get_config_int('height', 480)
        scale = self.get_config_float('scale', 0.5)
        interp_str = self.config.get('interpolation', 'linear')
        
        # Map interpolation string to OpenCV constant
        interp_map = {
            'nearest': cv2.INTER_NEAREST,
            'linear': cv2.INTER_LINEAR,
            'area': cv2.INTER_AREA,
            'cubic': cv2.INTER_CUBIC,
            'lanczos': cv2.INTER_LANCZOS4
        }
        interpolation = interp_map.get(interp_str, cv2.INTER_LINEAR)
        
        h, w = image.shape[:2]
        
        if mode == 'absolute':
            new_width = target_width
            new_height = target_height
        elif mode == 'scale':
            new_width = int(w * scale)
            new_height = int(h * scale)
        elif mode == 'fit':
            # Fit within bounds while maintaining aspect ratio
            ratio = min(target_width / w, target_height / h)
            new_width = int(w * ratio)
            new_height = int(h * ratio)
        elif mode == 'fill':
            # Fill bounds while maintaining aspect ratio (may crop)
            ratio = max(target_width / w, target_height / h)
            new_width = int(w * ratio)
            new_height = int(h * ratio)
        else:
            new_width = w
            new_height = h
        
        # Ensure minimum size
        new_width = max(1, new_width)
        new_height = max(1, new_height)
        
        result = cv2.resize(image, (new_width, new_height), interpolation=interpolation)
        
        # For fill mode, crop to target size
        if mode == 'fill':
            y_offset = (new_height - target_height) // 2
            x_offset = (new_width - target_width) // 2
            result = result[y_offset:y_offset + target_height, 
                           x_offset:x_offset + target_width]
        
        extra_fields = {
            'original_size': {'width': w, 'height': h},
            'new_size': {'width': result.shape[1], 'height': result.shape[0]}
        }
        
        return result, extra_fields
