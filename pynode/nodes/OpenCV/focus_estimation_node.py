"""
OpenCV Focus Estimation Node - measures image sharpness using various focus operators.
"""

import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, process_image, Info

_info = Info()
_info.add_text("Estimates image focus/sharpness using various computational methods. Outputs a focus score indicating how sharp the image is.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Source image"))
_info.add_header("Outputs")
_info.add_bullets(("Output 0:", "Message with focus score (and optionally the image)"))
_info.add_header("Focus Methods")
_info.add_bullets(
    ("Laplacian:", "Variance of Laplacian operator - best for general use"),
    ("Tenengrad:", "Sobel gradient magnitude - excellent edge detection"),
    ("Sobel + Variance:", "Combined gradient and variance - robust method"),
    ("Brenner Gradient:", "Pixel difference method - fast and simple"),
    ("Local Variance:", "Local intensity variations - works for high contrast"),
    ("Entropy:", "Shannon entropy - good for texture-rich images")
)
_info.add_header("Output")
_info.add_bullets(
    ("focus_score:", "Numerical sharpness value (higher = sharper)"),
    ("method:", "The focus estimation method used"),
    ("image:", "Original image (if 'Include Image' is enabled)")
)

class FocusEstimationNode(BaseNode):
    """
    Focus Estimation node - measures image sharpness using various focus operators.
    """
    info = str(_info)
    display_name = 'Focus Estimation'
    icon = '⌖'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'method': 'laplacian',
        'include_image': False
    }
    
    properties = [
        {
            'name': 'method',
            'label': 'Focus Method',
            'type': 'select',
            'options': [
                {'value': 'laplacian', 'label': 'Laplacian (Recommended)'},
                {'value': 'tenengrad', 'label': 'Tenengrad (Sobel)'},
                {'value': 'sobel_variance', 'label': 'Sobel + Variance'},
                {'value': 'brenner', 'label': 'Brenner Gradient'},
                {'value': 'variance', 'label': 'Local Variance'},
                {'value': 'entropy', 'label': 'Entropy'}
            ],
            'default': DEFAULT_CONFIG['method'],
            'help': 'Method to compute focus score'
        },
        {
            'name': 'include_image',
            'label': 'Include Image',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['include_image'],
            'help': 'Include image in output message'
        }
    ]
    
    def __init__(self, node_id=None, name="focus_estimation"):
        super().__init__(node_id, name)
    
    def _compute_laplacian(self, gray: np.ndarray) -> float:
        """
        Laplacian-based focus measure.
        Returns variance of Laplacian - sharp images have higher variance.
        """
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        return float(np.var(laplacian))
    
    def _compute_tenengrad(self, gray: np.ndarray) -> float:
        """
        Tenengrad (Sobel gradient) focus measure.
        Returns mean gradient magnitude - sharp images have stronger edges.
        """
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        tenengrad = np.sqrt(sobel_x**2 + sobel_y**2)
        return float(np.mean(tenengrad))
    
    def _compute_sobel_variance(self, gray: np.ndarray) -> float:
        """
        Combined Sobel + Variance focus measure.
        Returns sum of mean gradient magnitude and variance.
        """
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        sobel_magnitude = np.sqrt(sobel_x**2 + sobel_y**2)
        variance = np.var(gray)
        return float(np.mean(sobel_magnitude) + variance)
    
    def _compute_brenner_gradient(self, gray: np.ndarray) -> float:
        """
        Brenner gradient focus measure.
        Returns sum of squared differences between pixels 2 positions apart.
        """
        shifted = np.roll(gray, -2, axis=1)
        diff = (gray.astype(np.float64) - shifted.astype(np.float64)) ** 2
        return float(np.sum(diff))
    
    def _compute_local_variance(self, gray: np.ndarray, ksize: int = 5) -> float:
        """
        Local variance focus measure.
        Returns mean of local variance - sharp images have higher local variations.
        """
        gray_float = gray.astype(np.float64)
        mean = cv2.blur(gray_float, (ksize, ksize))
        squared_mean = cv2.blur(gray_float**2, (ksize, ksize))
        variance = squared_mean - (mean**2)
        return float(np.mean(variance))
    
    def _compute_entropy(self, gray: np.ndarray) -> float:
        """
        Entropy-based focus measure using Shannon entropy.
        Returns entropy value - sharp images have higher entropy.
        """
        # Compute histogram
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        hist = hist.flatten()
        
        # Normalize histogram to get probability distribution
        hist = hist / hist.sum()
        
        # Remove zero entries
        hist = hist[hist > 0]
        
        # Compute Shannon entropy
        entropy = -np.sum(hist * np.log2(hist))
        return float(entropy)
    
    @process_image()
    def on_input(self, image: np.ndarray, msg: Dict[str, Any], input_index: int = 0):
        """Compute focus score for the input image."""
        method = self.config.get('method', 'laplacian')
        include_image = self.get_config_bool('include_image', False)
        
        # Convert to grayscale for focus computation
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Compute focus score based on selected method
        if method == 'laplacian':
            focus_score = self._compute_laplacian(gray)
        elif method == 'tenengrad':
            focus_score = self._compute_tenengrad(gray)
        elif method == 'sobel_variance':
            focus_score = self._compute_sobel_variance(gray)
        elif method == 'brenner':
            focus_score = self._compute_brenner_gradient(gray)
        elif method == 'variance':
            focus_score = self._compute_local_variance(gray)
        elif method == 'entropy':
            focus_score = self._compute_entropy(gray)
        else:
            focus_score = self._compute_laplacian(gray)
        
        # Create output message with focus score
        output_msg = {'payload': {}}

        # Store the focus estimation results in msg.payload
        output_msg['payload'] = {
            'focus_score': focus_score,
            'method': method
        }
        
        # Include image if requested
        if include_image:
            output_msg['payload']['image'] = image
        
        # Send the message with focus information
        self.send(output_msg, 0)
        
        # Return None since we're sending a custom message
        return None
