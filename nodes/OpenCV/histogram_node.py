"""
OpenCV Histogram Node - computes and optionally equalizes image histograms.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode, process_image, Info

_info = Info()
_info.add_text("Computes histograms and applies histogram operations for contrast enhancement. For color images, operates on the L channel in LAB color space.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Image (color or grayscale)"))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Processed image"),
    ("msg.histogram:", "Array of 256 values representing pixel distribution")
)
_info.add_header("Operations")
_info.add_bullets(
    ("Compute only:", "Calculate histogram without modifying image"),
    ("Equalize:", "Standard histogram equalization for global contrast"),
    ("CLAHE:", "Adaptive equalization that prevents over-amplification"),
    ("Normalize:", "Stretch pixel values to specified range")
)
_info.add_header("Tips")
_info.add_bullets(
    ("CLAHE:", "Best for images with varying lighting conditions"),
    ("Clip Limit:", "Higher values = more contrast, may increase noise")
)


class HistogramNode(BaseNode):
    info = str(_info)
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
    
    DEFAULT_CONFIG = {
        'operation': 'equalize',
        'clip_limit': 2.0,
        'tile_size': 8,
        'normalize_alpha': 0,
        'normalize_beta': 255
    }
    
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
            'default': DEFAULT_CONFIG['operation'],
            'help': 'Histogram operation to perform'
        },
        {
            'name': 'clip_limit',
            'label': 'CLAHE Clip Limit',
            'type': 'number',
            'default': DEFAULT_CONFIG['clip_limit'],
            'min': 0.1,
            'max': 10,
            'step': 0.1,
            'help': 'Threshold for contrast limiting (CLAHE)',
            'showIf': {'operation': 'clahe'}
        },
        {
            'name': 'tile_size',
            'label': 'CLAHE Tile Size',
            'type': 'number',
            'default': DEFAULT_CONFIG['tile_size'],
            'min': 2,
            'max': 32,
            'help': 'Size of grid for CLAHE',
            'showIf': {'operation': 'clahe'}
        },
        {
            'name': 'normalize_alpha',
            'label': 'Normalize Alpha',
            'type': 'number',
            'default': DEFAULT_CONFIG['normalize_alpha'],
            'min': 0,
            'max': 255,
            'help': 'Lower bound for normalization',
            'showIf': {'operation': 'normalize'}
        },
        {
            'name': 'normalize_beta',
            'label': 'Normalize Beta',
            'type': 'number',
            'default': DEFAULT_CONFIG['normalize_beta'],
            'min': 0,
            'max': 255,
            'help': 'Upper bound for normalization',
            'showIf': {'operation': 'normalize'}
        }
    ]
    
    def __init__(self, node_id=None, name="histogram"):
        super().__init__(node_id, name)
    
    @process_image()
    def on_input(self, image: np.ndarray, msg: Dict[str, Any], input_index: int = 0):
        """Process image histogram."""
        operation = self.config.get('operation', 'equalize')
        clip_limit = self.get_config_float('clip_limit', 2.0)
        tile_size = self.get_config_int('tile_size', 8)
        alpha = self.get_config_int('normalize_alpha', 0)
        beta = self.get_config_int('normalize_beta', 255)
        
        # Convert to grayscale for processing if color
        if len(image.shape) == 3:
            is_color = True
            # Convert to LAB for better color handling
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l_channel = lab[:, :, 0]
        else:
            is_color = False
            l_channel = image
        
        # Compute histogram
        hist = cv2.calcHist([l_channel], [0], None, [256], [0, 256])
        extra_fields = {'histogram': hist.flatten().tolist()}
        
        if operation == 'compute':
            # Just compute, don't modify image
            return image, extra_fields
        
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
        
        return output, extra_fields
