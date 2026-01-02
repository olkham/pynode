"""
OpenCV Color Space Converter Node - converts between color spaces.
"""

import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, process_image, Info

_info = Info()
_info.add_text("Converts images between different color spaces.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Image to convert")
)
_info.add_header("Color Spaces")
_info.add_bullets(
    ("BGR:", "OpenCV default (Blue, Green, Red)"),
    ("RGB:", "Standard web format (Red, Green, Blue)"),
    ("HSV:", "Hue, Saturation, Value - good for color filtering"),
    ("HLS:", "Hue, Lightness, Saturation"),
    ("LAB:", "Perceptually uniform color space"),
    ("YUV:", "Luminance and chrominance separation"),
    ("Grayscale:", "Single channel intensity")
)
_info.add_header("Output")
_info.add_text("Outputs the converted image in the target color space.")


class ColorSpaceNode(BaseNode):
    """
    Color Space node - converts images between different color spaces.
    Supports BGR, RGB, HSV, HLS, LAB, YUV, and grayscale.
    """
    info = str(_info)
    display_name = 'Color Space'
    icon = '🎨'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'input_space': 'bgr',
        'output_space': 'gray'
    }
    
    properties = [
        {
            'name': 'input_space',
            'label': 'Input Color Space',
            'type': 'select',
            'options': [
                {'value': 'bgr', 'label': 'BGR'},
                {'value': 'rgb', 'label': 'RGB'},
                {'value': 'hsv', 'label': 'HSV'},
                {'value': 'hls', 'label': 'HLS'},
                {'value': 'lab', 'label': 'LAB'},
                {'value': 'yuv', 'label': 'YUV'},
                {'value': 'gray', 'label': 'Grayscale'}
            ],
            'default': DEFAULT_CONFIG['input_space'],
            'help': 'Input image color space'
        },
        {
            'name': 'output_space',
            'label': 'Output Color Space',
            'type': 'select',
            'options': [
                {'value': 'bgr', 'label': 'BGR'},
                {'value': 'rgb', 'label': 'RGB'},
                {'value': 'hsv', 'label': 'HSV'},
                {'value': 'hls', 'label': 'HLS'},
                {'value': 'lab', 'label': 'LAB'},
                {'value': 'yuv', 'label': 'YUV'},
                {'value': 'gray', 'label': 'Grayscale'}
            ],
            'default': DEFAULT_CONFIG['output_space'],
            'help': 'Output image color space'
        }
    ]
    
    def __init__(self, node_id=None, name="color space"):
        super().__init__(node_id, name)
    
    @process_image()
    def on_input(self, image: np.ndarray, msg: Dict[str, Any], input_index: int = 0):
        """Convert image color space."""
        input_space = self.config.get('input_space', 'bgr')
        output_space = self.config.get('output_space', 'gray')
        
        # No conversion needed if same
        if input_space == output_space:
            return image
        
        # Define conversion codes
        conversions = {
            ('bgr', 'rgb'): cv2.COLOR_BGR2RGB,
            ('bgr', 'gray'): cv2.COLOR_BGR2GRAY,
            ('bgr', 'hsv'): cv2.COLOR_BGR2HSV,
            ('bgr', 'hls'): cv2.COLOR_BGR2HLS,
            ('bgr', 'lab'): cv2.COLOR_BGR2LAB,
            ('bgr', 'yuv'): cv2.COLOR_BGR2YUV,
            ('rgb', 'bgr'): cv2.COLOR_RGB2BGR,
            ('rgb', 'gray'): cv2.COLOR_RGB2GRAY,
            ('rgb', 'hsv'): cv2.COLOR_RGB2HSV,
            ('rgb', 'hls'): cv2.COLOR_RGB2HLS,
            ('rgb', 'lab'): cv2.COLOR_RGB2LAB,
            ('rgb', 'yuv'): cv2.COLOR_RGB2YUV,
            ('hsv', 'bgr'): cv2.COLOR_HSV2BGR,
            ('hsv', 'rgb'): cv2.COLOR_HSV2RGB,
            ('hls', 'bgr'): cv2.COLOR_HLS2BGR,
            ('hls', 'rgb'): cv2.COLOR_HLS2RGB,
            ('lab', 'bgr'): cv2.COLOR_LAB2BGR,
            ('lab', 'rgb'): cv2.COLOR_LAB2RGB,
            ('yuv', 'bgr'): cv2.COLOR_YUV2BGR,
            ('yuv', 'rgb'): cv2.COLOR_YUV2RGB,
            ('gray', 'bgr'): cv2.COLOR_GRAY2BGR,
            ('gray', 'rgb'): cv2.COLOR_GRAY2RGB,
        }
        
        conversion_key = (input_space, output_space)
        
        if conversion_key in conversions:
            result = cv2.cvtColor(image, conversions[conversion_key])
        else:
            # Try two-step conversion via BGR
            if input_space != 'bgr' and (input_space, 'bgr') in conversions:
                temp = cv2.cvtColor(image, conversions[(input_space, 'bgr')])
                if ('bgr', output_space) in conversions:
                    result = cv2.cvtColor(temp, conversions[('bgr', output_space)])
                else:
                    result = temp
            else:
                result = image
        
        return result
