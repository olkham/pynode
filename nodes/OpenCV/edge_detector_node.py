"""
OpenCV Edge Detection Node - detects edges using various algorithms.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode, process_image


class EdgeDetectorNode(BaseNode):
    """
    Edge Detection node - detects edges in images.
    Supports Canny, Sobel, Laplacian, and Scharr methods.
    """
    display_name = 'Edge Detector'
    icon = '⧈'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'method': 'canny',
        'threshold1': 100,
        'threshold2': 200,
        'aperture_size': 3,
        'sobel_direction': 'both',
        'l2_gradient': 'no'
    }
    
    properties = [
        {
            'name': 'method',
            'label': 'Method',
            'type': 'select',
            'options': [
                {'value': 'canny', 'label': 'Canny'},
                {'value': 'sobel', 'label': 'Sobel'},
                {'value': 'laplacian', 'label': 'Laplacian'},
                {'value': 'scharr', 'label': 'Scharr'}
            ],
            'default': DEFAULT_CONFIG['method'],
            'help': 'Edge detection algorithm'
        },
        {
            'name': 'threshold1',
            'label': 'Threshold 1',
            'type': 'number',
            'default': DEFAULT_CONFIG['threshold1'],
            'min': 0,
            'max': 500,
            'help': 'First threshold for Canny hysteresis',
            'showIf': {'method': 'canny'}
        },
        {
            'name': 'threshold2',
            'label': 'Threshold 2',
            'type': 'number',
            'default': DEFAULT_CONFIG['threshold2'],
            'min': 0,
            'max': 500,
            'help': 'Second threshold for Canny hysteresis',
            'showIf': {'method': 'canny'}
        },
        {
            'name': 'aperture_size',
            'label': 'Aperture Size',
            'type': 'number',
            'default': DEFAULT_CONFIG['aperture_size'],
            'min': 3,
            'max': 7,
            'help': 'Aperture size for Sobel operator (3, 5, or 7)',
            'showIf': {'method': ['canny', 'sobel', 'laplacian']}
        },
        {
            'name': 'sobel_direction',
            'label': 'Sobel Direction',
            'type': 'select',
            'options': [
                {'value': 'both', 'label': 'Both X and Y'},
                {'value': 'x', 'label': 'X only'},
                {'value': 'y', 'label': 'Y only'}
            ],
            'default': DEFAULT_CONFIG['sobel_direction'],
            'help': 'Direction for Sobel/Scharr edge detection',
            'showIf': {'method': ['sobel', 'scharr']}
        },
        {
            'name': 'l2_gradient',
            'label': 'L2 Gradient (Canny)',
            'type': 'select',
            'options': [
                {'value': 'yes', 'label': 'Yes (more accurate)'},
                {'value': 'no', 'label': 'No (faster)'}
            ],
            'default': DEFAULT_CONFIG['l2_gradient'],
            'help': 'Use L2 norm for Canny gradient calculation',
            'showIf': {'method': 'canny'}
        }
    ]
    
    def __init__(self, node_id=None, name="edge detector"):
        super().__init__(node_id, name)
    
    @process_image()
    def on_input(self, image: np.ndarray, msg: Dict[str, Any], input_index: int = 0):
        """Detect edges in the input image."""
        method = self.config.get('method', 'canny')
        threshold1 = self.get_config_int('threshold1', 100)
        threshold2 = self.get_config_int('threshold2', 200)
        aperture = self.get_config_int('aperture_size', 3)
        direction = self.config.get('sobel_direction', 'both')
        l2_gradient = self.get_config_bool('l2_gradient', False)
        
        # Ensure aperture is valid (3, 5, or 7)
        if aperture not in [3, 5, 7]:
            aperture = 3
        
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        
        if method == 'canny':
            result = cv2.Canny(gray, threshold1, threshold2, 
                               apertureSize=aperture, L2gradient=l2_gradient)
        elif method == 'sobel':
            if direction == 'x':
                result = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=aperture)
            elif direction == 'y':
                result = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=aperture)
            else:
                sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=aperture)
                sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=aperture)
                result = cv2.magnitude(sobel_x, sobel_y)
            result = np.uint8(np.absolute(result))
        elif method == 'laplacian':
            result = cv2.Laplacian(gray, cv2.CV_64F, ksize=aperture)
            result = np.uint8(np.absolute(result))
        elif method == 'scharr':
            if direction == 'x':
                result = cv2.Scharr(gray, cv2.CV_64F, 1, 0)
            elif direction == 'y':
                result = cv2.Scharr(gray, cv2.CV_64F, 0, 1)
            else:
                scharr_x = cv2.Scharr(gray, cv2.CV_64F, 1, 0)
                scharr_y = cv2.Scharr(gray, cv2.CV_64F, 0, 1)
                result = cv2.magnitude(scharr_x, scharr_y)
            result = np.uint8(np.absolute(result))
        else:
            result = gray
        
        return result
