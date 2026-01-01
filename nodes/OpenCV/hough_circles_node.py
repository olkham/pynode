"""
OpenCV Hough Circles Node - detects circles in images.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Detects circles in images using the Hough Circle Transform. Applies median blur internally to reduce noise.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Image (color or grayscale)"))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Image with circles drawn (if enabled)"),
    ("msg.circles:", "Array of detected circles with x, y, radius")
)
_info.add_header("Key Parameters")
_info.add_bullets(
    ("DP:", "Accumulator resolution ratio (1 = same as image, 2 = half)"),
    ("Min Distance:", "Minimum distance between detected circle centers"),
    ("Canny Threshold:", "Higher threshold for internal Canny edge detection"),
    ("Accumulator Threshold:", "Lower = more circles detected (may include false positives)")
)
_info.add_header("Tips")
_info.add_bullets(
    ("No circles found?", "Try lowering Accumulator Threshold"),
    ("Too many false positives?", "Increase Accumulator Threshold or Min Distance")
)


class HoughCirclesNode(BaseNode):
    info = str(_info)
    """
    Hough Circles node - detects circles in images using Hough transform.
    """
    display_name = 'Hough Circles'
    icon = '◯'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'dp': 1.2,
        'min_dist': 50,
        'param1': 100,
        'param2': 30,
        'min_radius': 10,
        'max_radius': 0,
        'draw_circles': 'yes',
        'circle_color': '0,255,0'
    }
    
    properties = [
        {
            'name': 'dp',
            'label': 'DP (resolution ratio)',
            'type': 'number',
            'default': DEFAULT_CONFIG['dp'],
            'min': 1,
            'step': 0.1,
            'help': 'Inverse ratio of accumulator resolution (1 = same as image)'
        },
        {
            'name': 'min_dist',
            'label': 'Min Distance',
            'type': 'number',
            'default': DEFAULT_CONFIG['min_dist'],
            'min': 1,
            'help': 'Minimum distance between circle centers'
        },
        {
            'name': 'param1',
            'label': 'Canny Threshold',
            'type': 'number',
            'default': DEFAULT_CONFIG['param1'],
            'min': 1,
            'help': 'Higher threshold for Canny edge detector'
        },
        {
            'name': 'param2',
            'label': 'Accumulator Threshold',
            'type': 'number',
            'default': DEFAULT_CONFIG['param2'],
            'min': 1,
            'help': 'Accumulator threshold for circle detection'
        },
        {
            'name': 'min_radius',
            'label': 'Min Radius',
            'type': 'number',
            'default': DEFAULT_CONFIG['min_radius'],
            'min': 0,
            'help': 'Minimum circle radius (0 = no minimum)'
        },
        {
            'name': 'max_radius',
            'label': 'Max Radius',
            'type': 'number',
            'default': DEFAULT_CONFIG['max_radius'],
            'min': 0,
            'help': 'Maximum circle radius (0 = no maximum)'
        },
        {
            'name': 'draw_circles',
            'label': 'Draw Circles',
            'type': 'select',
            'options': [
                {'value': 'yes', 'label': 'Yes'},
                {'value': 'no', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['draw_circles'],
            'help': 'Draw detected circles on output'
        },
        {
            'name': 'circle_color',
            'label': 'Circle Color (B,G,R)',
            'type': 'text',
            'default': DEFAULT_CONFIG['circle_color'],
            'help': 'Color for drawn circles'
        }
    ]
    
    def __init__(self, node_id=None, name="hough circles"):
        super().__init__(node_id, name)
    
    def _parse_color(self, color_str):
        """Parse color string to BGR tuple."""
        try:
            parts = [int(x.strip()) for x in str(color_str).split(',')]
            if len(parts) >= 3:
                return (parts[0], parts[1], parts[2])
            return (0, 255, 0)
        except:
            return (0, 255, 0)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Detect circles in the input image."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        dp = self.get_config_float('dp', 1.2)
        min_dist = self.get_config_int('min_dist', 50)
        param1 = self.get_config_int('param1', 100)
        param2 = self.get_config_int('param2', 30)
        min_radius = self.get_config_int('min_radius', 10)
        max_radius = self.get_config_int('max_radius', 0)
        draw = self.get_config_bool('draw_circles', True)
        circle_color = self._parse_color(self.config.get('circle_color', '0,255,0'))
        
        # Convert to grayscale if needed
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        
        # Apply slight blur to reduce noise
        gray = cv2.medianBlur(gray, 5)
        
        # Detect circles
        circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp, min_dist,
                                   param1=param1, param2=param2,
                                   minRadius=min_radius, maxRadius=max_radius)
        
        circles_data = []
        if circles is not None:
            circles = np.uint16(np.around(circles))
            for circle in circles[0, :]:
                cx, cy, radius = circle
                circles_data.append({
                    'x': int(cx),
                    'y': int(cy),
                    'radius': int(radius),
                    'area': float(np.pi * radius * radius)
                })
            
            # Draw circles if requested
            if draw:
                if len(img.shape) == 2:
                    output = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                else:
                    output = img.copy()
                
                for circle in circles[0, :]:
                    cx, cy, radius = circle
                    cv2.circle(output, (cx, cy), radius, circle_color, 2)
                    cv2.circle(output, (cx, cy), 2, (0, 0, 255), 3)  # center
                
                if 'payload' not in msg or not isinstance(msg['payload'], dict):
                    msg['payload'] = {}
                msg['payload']['image'] = self.encode_image(output, format_type)
        
        msg['circles'] = circles_data
        msg['circle_count'] = len(circles_data)
        self.send(msg)
