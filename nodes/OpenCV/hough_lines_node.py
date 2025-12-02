"""
OpenCV Hough Lines Node - detects lines in images.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class HoughLinesNode(BaseNode):
    """
    Hough Lines node - detects lines in images using Hough transform.
    Works best on edge-detected images.
    """
    display_name = 'Hough Lines'
    icon = '╱'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'method',
            'label': 'Method',
            'type': 'select',
            'options': [
                {'value': 'standard', 'label': 'Standard'},
                {'value': 'probabilistic', 'label': 'Probabilistic'}
            ],
            'default': 'probabilistic',
            'help': 'Hough transform method'
        },
        {
            'name': 'rho',
            'label': 'Rho (pixels)',
            'type': 'number',
            'default': 1,
            'min': 1,
            'help': 'Distance resolution in pixels'
        },
        {
            'name': 'theta_degrees',
            'label': 'Theta (degrees)',
            'type': 'number',
            'default': 1,
            'min': 0.1,
            'step': 0.1,
            'help': 'Angle resolution in degrees'
        },
        {
            'name': 'threshold',
            'label': 'Threshold',
            'type': 'number',
            'default': 100,
            'min': 1,
            'help': 'Accumulator threshold'
        },
        {
            'name': 'min_length',
            'label': 'Min Line Length',
            'type': 'number',
            'default': 50,
            'min': 1,
            'help': 'Minimum line length (probabilistic only)'
        },
        {
            'name': 'max_gap',
            'label': 'Max Line Gap',
            'type': 'number',
            'default': 10,
            'min': 1,
            'help': 'Maximum gap between line segments (probabilistic only)'
        },
        {
            'name': 'draw_lines',
            'label': 'Draw Lines',
            'type': 'select',
            'options': [
                {'value': 'yes', 'label': 'Yes'},
                {'value': 'no', 'label': 'No'}
            ],
            'default': 'yes',
            'help': 'Draw detected lines on output'
        },
        {
            'name': 'line_color',
            'label': 'Line Color (B,G,R)',
            'type': 'text',
            'default': '0,0,255',
            'help': 'Color for drawn lines'
        }
    ]
    
    def __init__(self, node_id=None, name="hough lines"):
        super().__init__(node_id, name)
        self.configure({
            'method': 'probabilistic',
            'rho': 1,
            'theta_degrees': 1,
            'threshold': 100,
            'min_length': 50,
            'max_gap': 10,
            'draw_lines': 'yes',
            'line_color': '0,0,255'
        })
    
    def _parse_color(self, color_str):
        """Parse color string to BGR tuple."""
        try:
            parts = [int(x.strip()) for x in str(color_str).split(',')]
            if len(parts) >= 3:
                return (parts[0], parts[1], parts[2])
            return (0, 0, 255)
        except:
            return (0, 0, 255)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Detect lines in the input image."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        method = self.config.get('method', 'probabilistic')
        rho = float(self.config.get('rho', 1))
        theta = float(self.config.get('theta_degrees', 1)) * np.pi / 180
        threshold = int(self.config.get('threshold', 100))
        min_length = int(self.config.get('min_length', 50))
        max_gap = int(self.config.get('max_gap', 10))
        draw = self.config.get('draw_lines', 'yes') == 'yes'
        line_color = self._parse_color(self.config.get('line_color', '0,0,255'))
        
        # Convert to grayscale if needed
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        
        lines_data = []
        
        if method == 'standard':
            lines = cv2.HoughLines(gray, rho, theta, threshold)
            if lines is not None:
                for line in lines:
                    r, t = line[0]
                    lines_data.append({
                        'rho': float(r),
                        'theta': float(t),
                        'theta_degrees': float(t * 180 / np.pi)
                    })
        else:  # probabilistic
            lines = cv2.HoughLinesP(gray, rho, theta, threshold, 
                                    minLineLength=min_length, maxLineGap=max_gap)
            if lines is not None:
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    length = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
                    angle = np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi
                    lines_data.append({
                        'x1': int(x1), 'y1': int(y1),
                        'x2': int(x2), 'y2': int(y2),
                        'length': float(length),
                        'angle': float(angle)
                    })
        
        # Draw lines if requested
        if draw and lines is not None:
            if len(img.shape) == 2:
                output = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            else:
                output = img.copy()
            
            if method == 'standard':
                for line in lines:
                    r, t = line[0]
                    a, b = np.cos(t), np.sin(t)
                    x0, y0 = a * r, b * r
                    x1 = int(x0 + 1000 * (-b))
                    y1 = int(y0 + 1000 * (a))
                    x2 = int(x0 - 1000 * (-b))
                    y2 = int(y0 - 1000 * (a))
                    cv2.line(output, (x1, y1), (x2, y2), line_color, 2)
            else:
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    cv2.line(output, (x1, y1), (x2, y2), line_color, 2)
            
            if 'payload' not in msg or not isinstance(msg['payload'], dict):
                msg['payload'] = {}
            msg['payload']['image'] = self.encode_image(output, format_type)
        
        msg['lines'] = lines_data
        msg['line_count'] = len(lines_data)
        self.send(msg)
