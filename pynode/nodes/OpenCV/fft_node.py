"""
OpenCV FFT Node - performs Fast Fourier Transform on an image.
"""

import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Performs Fast Fourier Transform (FFT) on an input image to extract frequency components.")
_info.add_header("Inputs")
_info.add_bullet("Input 0:", "Input image (converted to grayscale automatically)")
_info.add_header("Outputs")
_info.add_bullet("Output 0:", "Magnitude Spectrum (visualizable) + FFT Complex Data (in metadata)")
_info.add_header("Notes")
_info.add_text("The complex frequency data is stored in the message metadata ('_fft_data') for downstream processing by the Frequency Filter node.")
_info.add_text("The visible output is the Magnitude Spectrum (log-scaled).")


class FFTNode(BaseNode):
    """
    FFT Node - converts image to frequency domain.
    """
    info = str(_info)
    display_name = 'FFT'
    icon = '∿'
    category = 'opencv'
    color = '#8E44AD'  # Purple-ish
    border_color = '#6C3483'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'output_view': 'magnitude'
    }
    
    properties = [
        {
            'name': 'output_view',
            'label': 'Output View',
            'type': 'select',
            'options': [
                {'value': 'magnitude', 'label': 'Magnitude Spectrum'}
            ],
            'default': DEFAULT_CONFIG['output_view'],
            'help': 'What to display in the image payload'
        }
    ]
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Process incoming image and compute FFT."""
        if MessageKeys.PAYLOAD not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg[MessageKeys.PAYLOAD])
        if img is None:
            self.send(msg)
            return
        
        if format_type is None:
            format_type = 'numpy_array'
            
        # Convert to grayscale if necessary
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
            
        # Compute DFT
        # cv2.dft expects float32
        dft = cv2.dft(np.float32(gray), flags=cv2.DFT_COMPLEX_OUTPUT)
        dft_shift = np.fft.fftshift(dft)
        
        # Compute Magnitude Spectrum for visualization
        # magnitude = sqrt(Re^2 + Im^2)
        magnitude = cv2.magnitude(dft_shift[:,:,0], dft_shift[:,:,1])
        
        # Log scale: 20 * log(1 + mag)
        magnitude_spectrum = 20 * np.log(magnitude + 1)
        
        # Normalize to 0-255
        cv2.normalize(magnitude_spectrum, magnitude_spectrum, 0, 255, cv2.NORM_MINMAX)
        result_img = np.uint8(magnitude_spectrum)
        
        # Create new message with result
        new_msg = msg.copy()
        
        # Encode result image
        if not isinstance(new_msg.get(MessageKeys.PAYLOAD), dict):
            new_msg[MessageKeys.PAYLOAD] = {}
            
        new_msg[MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH] = self.encode_image(result_img, format_type)
        
        # Store complex data for downstream nodes
        # Use a hidden key to pass the raw complex numpy array
        new_msg['_fft_data'] = dft_shift
        new_msg['_fft_shape'] = gray.shape  # Store original shape
        
        self.send(new_msg)
