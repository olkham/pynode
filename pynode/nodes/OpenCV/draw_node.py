"""
OpenCV Draw Node - draws shapes and annotations on images.
"""

import cv2
import numpy as np
from typing import Any, Dict, List
from pynode.nodes.base_node import BaseNode, process_image, Info

_info = Info()
_info.add_text("Draws shapes, text, and annotations on images. Supports rectangles, circles, lines, and text.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Image to draw on"))
_info.add_header("Outputs")
_info.add_bullets(("Output 0:", "Image with shapes drawn"))
_info.add_header("Coordinates")
_info.add_text("All coordinates are normalized (0.0-1.0), making drawings independent of image size.")
_info.add_bullets(
    ("0.0:", "Left/Top edge"),
    ("0.5:", "Center"),
    ("1.0:", "Right/Bottom edge")
)
_info.add_header("Shape Types")
_info.add_bullets(
    ("Rectangle:", "Uses X1,Y1 (top-left) and X2,Y2 (bottom-right)"),
    ("Circle:", "Uses X1,Y1 (center) and radius (relative to image width)"),
    ("Line:", "Uses X1,Y1 (start) and X2,Y2 (end)"),
    ("Text:", "Uses X1,Y1 (position) with text and font scale"),
    ("From message:", "Reads shapes from msg.shapes array")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Color:", "BGR format (e.g., 0,255,0 for green)"),
    ("Thickness:", "-1 for filled shapes")
)


class DrawNode(BaseNode):
    info = str(_info)
    """
    Draw node - draws shapes, text, and annotations on images.
    Can draw rectangles, circles, lines, and text.
    """
    display_name = 'Draw'
    icon = '✏'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'shape': 'rectangle',
        'x1': 0.1,
        'y1': 0.1,
        'x2': 0.3,
        'y2': 0.3,
        'radius': 0.1,
        'color': '0,255,0',
        'thickness': 2,
        'text': 'Hello',
        'font_scale': 1.0
    }
    
    properties = [
        {
            'name': 'shape',
            'label': 'Shape',
            'type': 'select',
            'options': [
                {'value': 'rectangle', 'label': 'Rectangle'},
                {'value': 'circle', 'label': 'Circle'},
                {'value': 'line', 'label': 'Line'},
                {'value': 'text', 'label': 'Text'},
                {'value': 'from_msg', 'label': 'From message (msg.shapes)'}
            ],
            'default': DEFAULT_CONFIG['shape'],
            'help': 'Shape to draw'
        },
        {
            'name': 'x1',
            'label': 'X1 / Center X',
            'type': 'number',
            'default': DEFAULT_CONFIG['x1'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.01,
            'help': 'Normalized X coordinate (0.0-1.0)',
            'showIf': {'shape': ['rectangle', 'circle', 'line', 'text']}
        },
        {
            'name': 'y1',
            'label': 'Y1 / Center Y',
            'type': 'number',
            'default': DEFAULT_CONFIG['y1'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.01,
            'help': 'Normalized Y coordinate (0.0-1.0)',
            'showIf': {'shape': ['rectangle', 'circle', 'line', 'text']}
        },
        {
            'name': 'x2',
            'label': 'X2',
            'type': 'number',
            'default': DEFAULT_CONFIG['x2'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.01,
            'help': 'Normalized X2 coordinate (0.0-1.0)',
            'showIf': {'shape': ['rectangle', 'line']}
        },
        {
            'name': 'y2',
            'label': 'Y2',
            'type': 'number',
            'default': DEFAULT_CONFIG['y2'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.01,
            'help': 'Normalized Y2 coordinate (0.0-1.0)',
            'showIf': {'shape': ['rectangle', 'line']}
        },
        {
            'name': 'radius',
            'label': 'Radius',
            'type': 'number',
            'default': DEFAULT_CONFIG['radius'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.01,
            'help': 'Normalized radius (relative to image width)',
            'showIf': {'shape': 'circle'}
        },
        {
            'name': 'color',
            'label': 'Color (B,G,R)',
            'type': 'text',
            'default': DEFAULT_CONFIG['color'],
            'help': 'Color as B,G,R values (e.g., 0,255,0 for green)'
        },
        {
            'name': 'thickness',
            'label': 'Thickness',
            'type': 'number',
            'default': DEFAULT_CONFIG['thickness'],
            'min': -1,
            'help': 'Line thickness (-1 for filled)'
        },
        {
            'name': 'text',
            'label': 'Text',
            'type': 'text',
            'default': DEFAULT_CONFIG['text'],
            'help': 'Text to draw',
            'showIf': {'shape': 'text'}
        },
        {
            'name': 'font_scale',
            'label': 'Font Scale',
            'type': 'number',
            'default': DEFAULT_CONFIG['font_scale'],
            'min': 0.1,
            'step': 0.1,
            'help': 'Font scale for text',
            'showIf': {'shape': 'text'}
        }
    ]
    
    def __init__(self, node_id=None, name="draw"):
        super().__init__(node_id, name)
        self.configure({
            'shape': 'rectangle',
            'x1': 0.1,
            'y1': 0.1,
            'x2': 0.3,
            'y2': 0.3,
            'radius': 0.1,
            'color': '0,255,0',
            'thickness': 2,
            'text': 'Hello',
            'font_scale': 1.0
        })
    
    def _parse_color(self, color_str):
        """Parse color string to BGR tuple."""
        try:
            parts = [int(x.strip()) for x in str(color_str).split(',')]
            if len(parts) >= 3:
                return (parts[0], parts[1], parts[2])
            return (0, 255, 0)
        except:
            return (0, 255, 0)
    
    def _draw_shape(self, img, shape_info):
        """Draw a single shape on the image using normalized coordinates."""
        h, w = img.shape[:2]
        shape_type = shape_info.get('type', 'rectangle')
        color = self._parse_color(shape_info.get('color', '0,255,0'))
        thickness = int(shape_info.get('thickness', 2))
        
        if shape_type == 'rectangle':
            x1 = int(float(shape_info.get('x1', 0)) * w)
            y1 = int(float(shape_info.get('y1', 0)) * h)
            x2 = int(float(shape_info.get('x2', 0.1)) * w)
            y2 = int(float(shape_info.get('y2', 0.1)) * h)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
        
        elif shape_type == 'circle':
            cx = int(float(shape_info.get('x1', shape_info.get('cx', 0.5))) * w)
            cy = int(float(shape_info.get('y1', shape_info.get('cy', 0.5))) * h)
            radius = int(float(shape_info.get('radius', 0.1)) * w)
            cv2.circle(img, (cx, cy), radius, color, thickness)
        
        elif shape_type == 'line':
            x1 = int(float(shape_info.get('x1', 0)) * w)
            y1 = int(float(shape_info.get('y1', 0)) * h)
            x2 = int(float(shape_info.get('x2', 0.1)) * w)
            y2 = int(float(shape_info.get('y2', 0.1)) * h)
            cv2.line(img, (x1, y1), (x2, y2), color, thickness)
        
        elif shape_type == 'text':
            x = int(float(shape_info.get('x1', shape_info.get('x', 0.1))) * w)
            y = int(float(shape_info.get('y1', shape_info.get('y', 0.1))) * h)
            text = str(shape_info.get('text', ''))
            font_scale = float(shape_info.get('font_scale', 1.0))
            cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 
                       font_scale, color, thickness)
        
        return img
    
    @process_image()
    def on_input(self, image: np.ndarray, msg: Dict[str, Any], input_index: int = 0):
        """Draw shapes on the input image."""
        # Make a copy to draw on
        result = image.copy()
        
        shape = self.config.get('shape', 'rectangle')
        
        if shape == 'from_msg':
            # Draw shapes from message
            shapes = msg.get('shapes', [])
            for shape_info in shapes:
                result = self._draw_shape(result, shape_info)
        else:
            # Draw configured shape
            shape_info = {
                'type': shape,
                'x1': self.config.get('x1', 0.1),
                'y1': self.config.get('y1', 0.1),
                'x2': self.config.get('x2', 0.3),
                'y2': self.config.get('y2', 0.3),
                'radius': self.config.get('radius', 0.1),
                'color': self.config.get('color', '0,255,0'),
                'thickness': self.config.get('thickness', 2),
                'text': self.config.get('text', 'Hello'),
                'font_scale': self.config.get('font_scale', 1.0)
            }
            result = self._draw_shape(result, shape_info)
        
        return result
