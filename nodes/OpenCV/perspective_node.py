"""
OpenCV Perspective Transform Node - applies perspective transformations.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class PerspectiveNode(BaseNode):
    """
    Perspective Transform node - applies perspective/warp transformations.
    Can correct perspective distortion or apply custom warps.
    """
    display_name = 'Perspective'
    icon = '⬱'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'mode',
            'label': 'Mode',
            'type': 'select',
            'options': [
                {'value': 'from_msg', 'label': 'Points from message'},
                {'value': 'manual', 'label': 'Manual points'}
            ],
            'default': 'from_msg',
            'help': 'How to get source points'
        },
        {
            'name': 'output_width',
            'label': 'Output Width',
            'type': 'number',
            'default': 400,
            'min': 1,
            'help': 'Width of output image'
        },
        {
            'name': 'output_height',
            'label': 'Output Height',
            'type': 'number',
            'default': 300,
            'min': 1,
            'help': 'Height of output image'
        },
        {
            'name': 'src_points',
            'label': 'Source Points',
            'type': 'text',
            'default': '0,0;100,0;100,100;0,100',
            'help': 'Source points as x1,y1;x2,y2;x3,y3;x4,y4 (TL,TR,BR,BL)',
            'showIf': {'mode': 'manual'}
        }
    ]
    
    def __init__(self, node_id=None, name="perspective"):
        super().__init__(node_id, name)
        self.configure({
            'mode': 'from_msg',
            'output_width': 400,
            'output_height': 300,
            'src_points': '0,0;100,0;100,100;0,100'
        })
    
    def _parse_points(self, points_str):
        """Parse points string to numpy array."""
        try:
            points = []
            for pt in points_str.split(';'):
                x, y = pt.strip().split(',')
                points.append([float(x), float(y)])
            return np.float32(points)
        except:
            return None
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Apply perspective transform."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        mode = self.config.get('mode', 'from_msg')
        output_w = int(self.config.get('output_width', 400))
        output_h = int(self.config.get('output_height', 300))
        
        # Get source points
        if mode == 'from_msg':
            src_points = msg.get('perspective_points')
            if src_points is None:
                src_points = msg.get('src_points')
            if src_points is None:
                self.send(msg)
                return
            if isinstance(src_points, str):
                src_pts = self._parse_points(src_points)
            elif isinstance(src_points, list):
                src_pts = np.float32(src_points)
            else:
                src_pts = src_points
        else:
            src_pts = self._parse_points(self.config.get('src_points', ''))
        
        if src_pts is None or len(src_pts) != 4:
            self.send(msg)
            return
        
        # Define destination points (rectangle)
        dst_pts = np.float32([
            [0, 0],
            [output_w - 1, 0],
            [output_w - 1, output_h - 1],
            [0, output_h - 1]
        ])
        
        # Compute perspective transform matrix
        M = cv2.getPerspectiveTransform(src_pts, dst_pts)
        
        # Apply warp
        result = cv2.warpPerspective(img, M, (output_w, output_h))
        
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(result, format_type)
        msg['transform_matrix'] = M.tolist()
        self.send(msg)
