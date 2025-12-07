"""
OpenCV Morphology Node - applies morphological operations to images.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode, process_image


class MorphologyNode(BaseNode):
    """
    Morphology node - applies morphological operations to binary/grayscale images.
    Supports erosion, dilation, opening, closing, gradient, tophat, and blackhat.
    """
    display_name = 'Morphology'
    icon = '⬡'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'operation': 'dilate',
        'kernel_shape': 'rect',
        'kernel_size': 5,
        'iterations': 1
    }
    
    properties = [
        {
            'name': 'operation',
            'label': 'Operation',
            'type': 'select',
            'options': [
                {'value': 'erode', 'label': 'Erode'},
                {'value': 'dilate', 'label': 'Dilate'},
                {'value': 'open', 'label': 'Open (erode then dilate)'},
                {'value': 'close', 'label': 'Close (dilate then erode)'},
                {'value': 'gradient', 'label': 'Gradient'},
                {'value': 'tophat', 'label': 'Top Hat'},
                {'value': 'blackhat', 'label': 'Black Hat'}
            ],
            'default': DEFAULT_CONFIG['operation'],
            'help': 'Morphological operation to apply'
        },
        {
            'name': 'kernel_shape',
            'label': 'Kernel Shape',
            'type': 'select',
            'options': [
                {'value': 'rect', 'label': 'Rectangle'},
                {'value': 'ellipse', 'label': 'Ellipse'},
                {'value': 'cross', 'label': 'Cross'}
            ],
            'default': DEFAULT_CONFIG['kernel_shape'],
            'help': 'Shape of the structuring element'
        },
        {
            'name': 'kernel_size',
            'label': 'Kernel Size',
            'type': 'number',
            'default': DEFAULT_CONFIG['kernel_size'],
            'min': 1,
            'max': 99,
            'help': 'Size of the structuring element'
        },
        {
            'name': 'iterations',
            'label': 'Iterations',
            'type': 'number',
            'default': DEFAULT_CONFIG['iterations'],
            'min': 1,
            'max': 20,
            'help': 'Number of times to apply the operation'
        }
    ]
    
    def __init__(self, node_id=None, name="morphology"):
        super().__init__(node_id, name)
    
    @process_image()
    def on_input(self, image: np.ndarray, msg: Dict[str, Any], input_index: int = 0):
        """Apply morphological operation to the input image."""
        operation = self.config.get('operation', 'dilate')
        kernel_shape = self.config.get('kernel_shape', 'rect')
        kernel_size = self.get_config_int('kernel_size', 5)
        iterations = self.get_config_int('iterations', 1)
        
        # Create structuring element
        shape_map = {
            'rect': cv2.MORPH_RECT,
            'ellipse': cv2.MORPH_ELLIPSE,
            'cross': cv2.MORPH_CROSS
        }
        shape = shape_map.get(kernel_shape, cv2.MORPH_RECT)
        kernel = cv2.getStructuringElement(shape, (kernel_size, kernel_size))
        
        # Apply operation
        if operation == 'erode':
            result = cv2.erode(image, kernel, iterations=iterations)
        elif operation == 'dilate':
            result = cv2.dilate(image, kernel, iterations=iterations)
        elif operation == 'open':
            result = cv2.morphologyEx(image, cv2.MORPH_OPEN, kernel, iterations=iterations)
        elif operation == 'close':
            result = cv2.morphologyEx(image, cv2.MORPH_CLOSE, kernel, iterations=iterations)
        elif operation == 'gradient':
            result = cv2.morphologyEx(image, cv2.MORPH_GRADIENT, kernel, iterations=iterations)
        elif operation == 'tophat':
            result = cv2.morphologyEx(image, cv2.MORPH_TOPHAT, kernel, iterations=iterations)
        elif operation == 'blackhat':
            result = cv2.morphologyEx(image, cv2.MORPH_BLACKHAT, kernel, iterations=iterations)
        else:
            result = image
        
        return result
