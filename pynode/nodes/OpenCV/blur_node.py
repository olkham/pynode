"""
OpenCV Blur Node - applies various blur/smoothing filters to images.
"""

import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, process_image, Info, MessageKeys

_info = Info()
_info.add_text("Applies blur/smoothing filters to images for noise reduction or artistic effects.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Image to blur")
)
_info.add_header("Methods")
_info.add_bullets(
    ("Gaussian:", "Standard smooth blur, good for noise reduction"),
    ("Median:", "Preserves edges, excellent for salt-and-pepper noise"),
    ("Bilateral:", "Edge-preserving smoothing, maintains sharp edges"),
    ("Box:", "Simple average blur, fast but less smooth"),
    ("Stack:", "Fast approximation of Gaussian blur")
)
_info.add_header("Output")
_info.add_text("Outputs the blurred image.")


class BlurNode(BaseNode):
    """
    Blur node - applies smoothing/blur filters to images.
    Supports Gaussian, median, bilateral, and box blur.
    """
    info = str(_info)
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
    
    @process_image()
    def on_input(self, image: np.ndarray, msg: Dict[str, Any], input_index: int = 0):
        """Apply blur to the input image."""
        method = self.config.get('method', 'gaussian')
        ksize = self.get_config_int('kernel_size', 5)
        sigma = self.get_config_float('sigma', 0)
        sigma_color = self.get_config_float('sigma_color', 75)
        sigma_space = self.get_config_float('sigma_space', 75)
        
        # Ensure kernel size is odd for methods that require it
        if ksize % 2 == 0:
            ksize += 1
        
        if method == 'gaussian':
            result = cv2.GaussianBlur(image, (ksize, ksize), sigma)
        elif method == 'median':
            result = cv2.medianBlur(image, ksize)
        elif method == 'bilateral':
            result = cv2.bilateralFilter(image, ksize, sigma_color, sigma_space)
        elif method == 'box':
            result = cv2.blur(image, (ksize, ksize))
        elif method == 'stack':
            result = cv2.stackBlur(image, (ksize, ksize))
        else:
            result = image
        
        # Preserve bbox if present (for crop workflows)
        extra_fields = {}
        if isinstance(msg.get(MessageKeys.PAYLOAD), dict):
            bbox = msg[MessageKeys.PAYLOAD].get('bbox')
            if bbox is not None:
                # Keep bbox in payload and add to msg level for PasteNode
                extra_fields['bbox'] = {'x1': bbox[0], 'y1': bbox[1], 'x2': bbox[2], 'y2': bbox[3]}
        
        return result, extra_fields
