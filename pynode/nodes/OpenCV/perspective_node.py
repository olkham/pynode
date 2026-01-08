"""
OpenCV Perspective Transform Node - applies perspective transformations.
"""

import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Applies perspective transformation to correct distortion or create custom warps. Transforms a quadrilateral region to a rectangular output.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Source image"))
_info.add_header("Outputs")
_info.add_bullets(("Output 0:", "Warped image with perspective corrected"))
_info.add_header("Normalized Coordinates")
_info.add_text("Source points use normalized coordinates (0.0-1.0):")
_info.add_bullets(
    ("0.0:", "Left/Top edge"),
    ("0.5:", "Center"),
    ("1.0:", "Right/Bottom edge")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Mode:", "Get source points from message or manual entry"),
    ("Output Size:", "Width and height of the output image"),
    ("Source Points:", "Four corners as x1,y1;x2,y2;x3,y3;x4,y4 (TL,TR,BR,BL) in normalized coords")
)
_info.add_header("Message Fields")
_info.add_bullets(
    ("perspective_points:", "Source points from upstream node"),
    ("transform_matrix:", "Output transformation matrix")
)

class PerspectiveNode(BaseNode):
    """
    Perspective Transform node - applies perspective/warp transformations.
    Can correct perspective distortion or apply custom warps.
    """
    info = str(_info)
    display_name = 'Perspective'
    icon = '⬱'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'mode': 'from_msg',
        'output_width': 400,
        'output_height': 300,
        'src_points': '0.0,0.0;0.25,0.0;0.25,0.33;0.0,0.33'
    }
    
    properties = [
        {
            'name': 'mode',
            'label': 'Mode',
            'type': 'select',
            'options': [
                {'value': 'from_msg', 'label': 'Points from message'},
                {'value': 'manual', 'label': 'Manual points'}
            ],
            'default': DEFAULT_CONFIG['mode'],
            'help': 'How to get source points'
        },
        {
            'name': 'output_width',
            'label': 'Output Width',
            'type': 'number',
            'default': DEFAULT_CONFIG['output_width'],
            'min': 1,
            'help': 'Width of output image in pixels'
        },
        {
            'name': 'output_height',
            'label': 'Output Height',
            'type': 'number',
            'default': DEFAULT_CONFIG['output_height'],
            'min': 1,
            'help': 'Height of output image in pixels'
        },
        {
            'name': 'src_points',
            'label': 'Source Points',
            'type': 'text',
            'default': DEFAULT_CONFIG['src_points'],
            'help': 'Normalized source points (0.0-1.0) as x1,y1;x2,y2;x3,y3;x4,y4 (TL,TR,BR,BL)',
            'showIf': {'mode': 'manual'}
        }
    ]
    
    def __init__(self, node_id=None, name="perspective"):
        super().__init__(node_id, name)
    
    def _parse_points(self, points_str, img_w=1, img_h=1):
        """Parse points string to numpy array. Converts normalized coords to pixels."""
        try:
            points = []
            for pt in points_str.split(';'):
                x, y = pt.strip().split(',')
                x, y = float(x), float(y)
                # Convert normalized (0.0-1.0) to pixel coordinates
                if x <= 1.0 and y <= 1.0:
                    x = x * img_w
                    y = y * img_h
                points.append([x, y])
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
        
        h, w = img.shape[:2]
        mode = self.config.get('mode', 'from_msg')
        output_w = self.get_config_int('output_width', 400)
        output_h = self.get_config_int('output_height', 300)
        
        # Get source points
        if mode == 'from_msg':
            src_points = msg.get('perspective_points')
            if src_points is None:
                src_points = msg.get('src_points')
            if src_points is None:
                self.send(msg)
                return
            if isinstance(src_points, str):
                src_pts = self._parse_points(src_points, w, h)
            elif isinstance(src_points, list):
                # Assume normalized if values are <= 1.0, otherwise pixel coords
                flat = [v for pt in src_points for v in (pt if isinstance(pt, (list, tuple)) else [pt])]
                if all(0 <= v <= 1.0 for v in flat):
                    src_pts = np.float32([[pt[0] * w, pt[1] * h] for pt in src_points])
                else:
                    src_pts = np.float32(src_points)
            else:
                src_pts = src_points
        else:
            src_pts = self._parse_points(self.config.get('src_points', ''), w, h)
        
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
