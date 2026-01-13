"""
OpenCV Arithmetic Operations Node - performs pixel-wise arithmetic operations on images.
"""

import cv2
import numpy as np
from typing import Any, Dict, Optional
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Performs pixel-wise arithmetic operations between two images or with a constant value.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "First image (primary)"),
    ("Input 1:", "Second image (optional, for image-to-image operations)")
)
_info.add_header("Operations")
_info.add_bullets(
    ("Add:", "Adds pixel values (saturated to max value)"),
    ("Subtract:", "Subtracts pixel values (saturated to 0)"),
    ("Multiply:", "Multiplies pixel values"),
    ("Divide:", "Divides pixel values"),
    ("Weighted Add:", "Blends two images with alpha weights"),
    ("Absolute Difference:", "Absolute difference between images"),
    ("Min:", "Minimum of two images pixel-wise"),
    ("Max:", "Maximum of two images pixel-wise")
)
_info.add_header("Modes")
_info.add_bullets(
    ("Image + Image:", "Operate between two input images"),
    ("Image + Constant:", "Operate with a constant scalar value")
)
_info.add_header("Output")
_info.add_text("Outputs the resulting image from the arithmetic operation.")


class ArithmeticNode(BaseNode):
    """
    Arithmetic node - performs pixel-wise arithmetic operations on images.
    Supports operations between two images or with a constant value.
    """
    info = str(_info)
    display_name = 'Arithmetic'
    icon = '±'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 2  # Input 0: image1, Input 1: image2 (optional)
    output_count = 1
    
    DEFAULT_CONFIG = {
        'operation': 'add',
        'mode': 'image',
        'constant': '50',
        'alpha': '0.5',
        'beta': '0.5',
        'gamma': '0',
        'auto_resize': 'true',
        'resize_method': 'resize_second',
        'clip_output': 'true'
    }
    
    properties = [
        {
            'name': 'operation',
            'label': 'Operation',
            'type': 'select',
            'options': [
                {'value': 'add', 'label': 'Add'},
                {'value': 'subtract', 'label': 'Subtract'},
                {'value': 'multiply', 'label': 'Multiply'},
                {'value': 'divide', 'label': 'Divide'},
                {'value': 'weighted_add', 'label': 'Weighted Add (Blend)'},
                {'value': 'absdiff', 'label': 'Absolute Difference'},
                {'value': 'min', 'label': 'Minimum'},
                {'value': 'max', 'label': 'Maximum'},
                {'value': 'power', 'label': 'Power'},
                {'value': 'sqrt', 'label': 'Square Root (single image)'}
            ],
            'default': DEFAULT_CONFIG['operation'],
            'help': 'Arithmetic operation to perform'
        },
        {
            'name': 'mode',
            'label': 'Mode',
            'type': 'select',
            'options': [
                {'value': 'image', 'label': 'Image + Image'},
                {'value': 'constant', 'label': 'Image + Constant'}
            ],
            'default': DEFAULT_CONFIG['mode'],
            'help': 'Operate between images or with a constant value'
        },
        {
            'name': 'constant',
            'label': 'Constant Value',
            'type': 'text',
            'default': DEFAULT_CONFIG['constant'],
            'help': 'Scalar value for constant mode (can be negative for subtract)'
        },
        {
            'name': 'alpha',
            'label': 'Alpha (Weight 1)',
            'type': 'text',
            'default': DEFAULT_CONFIG['alpha'],
            'help': 'Weight for first image in weighted add (0.0-1.0)'
        },
        {
            'name': 'beta',
            'label': 'Beta (Weight 2)',
            'type': 'text',
            'default': DEFAULT_CONFIG['beta'],
            'help': 'Weight for second image in weighted add (0.0-1.0)'
        },
        {
            'name': 'gamma',
            'label': 'Gamma (Offset)',
            'type': 'text',
            'default': DEFAULT_CONFIG['gamma'],
            'help': 'Scalar added to weighted sum'
        },
        {
            'name': 'auto_resize',
            'label': 'Auto Resize',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes'},
                {'value': 'false', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['auto_resize'],
            'help': 'Automatically resize images to match dimensions'
        },
        {
            'name': 'resize_method',
            'label': 'Resize Method',
            'type': 'select',
            'options': [
                {'value': 'resize_second', 'label': 'Resize second to match first'},
                {'value': 'resize_first', 'label': 'Resize first to match second'},
                {'value': 'resize_larger', 'label': 'Resize to larger dimensions'},
                {'value': 'resize_smaller', 'label': 'Resize to smaller dimensions'}
            ],
            'default': DEFAULT_CONFIG['resize_method'],
            'help': 'How to handle size mismatch between images'
        },
        {
            'name': 'clip_output',
            'label': 'Clip Output',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes (0-255)'},
                {'value': 'false', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['clip_output'],
            'help': 'Clip output values to valid range (0-255)'
        }
    ]
    
    def __init__(self, node_id=None, name="arithmetic"):
        super().__init__(node_id, name)
        self._image1: Optional[np.ndarray] = None
        self._image2: Optional[np.ndarray] = None
        self._format_type: Optional[str] = None
        self._last_msg: Optional[Dict] = None
    
    def _resize_images(self, img1: np.ndarray, img2: np.ndarray) -> tuple:
        """Resize images based on configuration."""
        if img1.shape[:2] == img2.shape[:2]:
            return img1, img2
        
        auto_resize = self.config.get('auto_resize', 'true') == 'true'
        if not auto_resize:
            # Just resize second to first as fallback
            img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
            return img1, img2
        
        resize_method = self.config.get('resize_method', 'resize_second')
        
        h1, w1 = img1.shape[:2]
        h2, w2 = img2.shape[:2]
        
        if resize_method == 'resize_second':
            img2 = cv2.resize(img2, (w1, h1))
        elif resize_method == 'resize_first':
            img1 = cv2.resize(img1, (w2, h2))
        elif resize_method == 'resize_larger':
            target_w = max(w1, w2)
            target_h = max(h1, h2)
            if (h1, w1) != (target_h, target_w):
                img1 = cv2.resize(img1, (target_w, target_h))
            if (h2, w2) != (target_h, target_w):
                img2 = cv2.resize(img2, (target_w, target_h))
        elif resize_method == 'resize_smaller':
            target_w = min(w1, w2)
            target_h = min(h1, h2)
            if (h1, w1) != (target_h, target_w):
                img1 = cv2.resize(img1, (target_w, target_h))
            if (h2, w2) != (target_h, target_w):
                img2 = cv2.resize(img2, (target_w, target_h))
        
        return img1, img2
    
    def _match_channels(self, img1: np.ndarray, img2: np.ndarray) -> tuple:
        """Ensure both images have the same number of channels."""
        c1 = img1.shape[2] if len(img1.shape) == 3 else 1
        c2 = img2.shape[2] if len(img2.shape) == 3 else 1
        
        if c1 == c2:
            return img1, img2
        
        # Convert grayscale to BGR if needed
        if c1 == 1 and c2 == 3:
            img1 = cv2.cvtColor(img1, cv2.COLOR_GRAY2BGR)
        elif c1 == 3 and c2 == 1:
            img2 = cv2.cvtColor(img2, cv2.COLOR_GRAY2BGR)
        
        return img1, img2
    
    def _create_constant_image(self, img: np.ndarray, value: float) -> np.ndarray:
        """Create a constant image matching the input dimensions."""
        const_img = np.full_like(img, abs(value), dtype=np.float32)
        return const_img
    
    def _perform_operation(self, img1: np.ndarray, img2: Optional[np.ndarray]) -> np.ndarray:
        """Perform the configured arithmetic operation."""
        operation = self.config.get('operation', 'add')
        mode = self.config.get('mode', 'image')
        clip_output = self.config.get('clip_output', 'true') == 'true'
        
        # Convert to float for precision
        img1_f = img1.astype(np.float32)
        
        # Handle single-image operations
        if operation == 'sqrt':
            result = np.sqrt(img1_f)
            if clip_output:
                result = np.clip(result, 0, 255)
            return result.astype(np.uint8)
        
        # Get second operand (image or constant)
        if mode == 'constant':
            try:
                const_value = float(self.config.get('constant', '50'))
            except ValueError:
                const_value = 50.0
            img2_f = self._create_constant_image(img1, const_value)
        else:
            if img2 is None:
                return img1
            img1, img2 = self._resize_images(img1, img2)
            img1, img2 = self._match_channels(img1, img2)
            img1_f = img1.astype(np.float32)
            img2_f = img2.astype(np.float32)
        
        # Perform operation
        if operation == 'add':
            result = cv2.add(img1, img2 if mode == 'image' else img2_f.astype(np.uint8))
        elif operation == 'subtract':
            if mode == 'constant':
                const_value = float(self.config.get('constant', '50'))
                if const_value >= 0:
                    result = cv2.subtract(img1, img2_f.astype(np.uint8))
                else:
                    # Negative constant means add
                    result = cv2.add(img1, np.full_like(img1, abs(const_value), dtype=np.uint8))
            else:
                result = cv2.subtract(img1, img2)
        elif operation == 'multiply':
            # Scale factor for multiply
            result = img1_f * (img2_f / 255.0 if mode == 'image' else img2_f / 255.0)
            if clip_output:
                result = np.clip(result, 0, 255)
            result = result.astype(np.uint8)
        elif operation == 'divide':
            # Avoid division by zero
            img2_safe = np.where(img2_f == 0, 1, img2_f)
            if mode == 'constant':
                result = img1_f / (img2_safe / 255.0) if img2_f.mean() != 0 else img1_f
            else:
                result = (img1_f / img2_safe) * 255.0
            if clip_output:
                result = np.clip(result, 0, 255)
            result = result.astype(np.uint8)
        elif operation == 'weighted_add':
            try:
                alpha = float(self.config.get('alpha', '0.5'))
                beta = float(self.config.get('beta', '0.5'))
                gamma = float(self.config.get('gamma', '0'))
            except ValueError:
                alpha, beta, gamma = 0.5, 0.5, 0.0
            
            if mode == 'constant':
                result = cv2.addWeighted(img1, alpha, img2_f.astype(np.uint8), beta, gamma)
            else:
                result = cv2.addWeighted(img1, alpha, img2, beta, gamma)
        elif operation == 'absdiff':
            if mode == 'constant':
                result = cv2.absdiff(img1, img2_f.astype(np.uint8))
            else:
                result = cv2.absdiff(img1, img2)
        elif operation == 'min':
            if mode == 'constant':
                result = np.minimum(img1_f, img2_f)
            else:
                result = np.minimum(img1_f, img2_f)
            result = result.astype(np.uint8)
        elif operation == 'max':
            if mode == 'constant':
                result = np.maximum(img1_f, img2_f)
            else:
                result = np.maximum(img1_f, img2_f)
            result = result.astype(np.uint8)
        elif operation == 'power':
            try:
                const_value = float(self.config.get('constant', '2'))
            except ValueError:
                const_value = 2.0
            # Normalize, apply power, denormalize
            result = np.power(img1_f / 255.0, const_value) * 255.0
            if clip_output:
                result = np.clip(result, 0, 255)
            result = result.astype(np.uint8)
        else:
            result = img1
        
        return result
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Process incoming image and perform arithmetic operation."""
        if MessageKeys.PAYLOAD not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg[MessageKeys.PAYLOAD])
        if img is None:
            self.send(msg)
            return
        
        # Store image based on input index
        if input_index == 0:
            self._image1 = img
            self._format_type = format_type
            self._last_msg = msg.copy()
        else:
            self._image2 = img
        
        operation = self.config.get('operation', 'add')
        mode = self.config.get('mode', 'image')
        
        # Single-image operations (sqrt) only need image1
        if operation == 'sqrt' and self._image1 is not None:
            result = self._perform_operation(self._image1, None)
            self._send_result(result, msg)
            return
        
        # Constant mode only needs image1
        if mode == 'constant' and self._image1 is not None:
            result = self._perform_operation(self._image1, None)
            self._send_result(result, self._last_msg or msg)
            return
        
        # Image mode needs both images
        if mode == 'image' and self._image1 is not None and self._image2 is not None:
            result = self._perform_operation(self._image1, self._image2)
            self._send_result(result, self._last_msg or msg)
            # Reset for next pair
            self._image1 = None
            self._image2 = None
    
    def _send_result(self, result: np.ndarray, msg: Dict[str, Any]):
        """Send the result image."""
        if MessageKeys.PAYLOAD not in msg or not isinstance(msg[MessageKeys.PAYLOAD], dict):
            msg[MessageKeys.PAYLOAD] = {}
        msg[MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH] = self.encode_image(result, self._format_type)
        self.send(msg)
