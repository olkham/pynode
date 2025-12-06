"""
OpenCV Draw Node - draws shapes and annotations on images.
"""

import cv2
import numpy as np
from typing import Any, Dict, List
from nodes.base_node import BaseNode


class DrawNode(BaseNode):
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
        'x1': 100,
        'y1': 100,
        'x2': 200,
        'y2': 200,
        'radius': 50,
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
            'help': 'X coordinate (start point or center)',
            'showIf': {'shape': ['rectangle', 'circle', 'line', 'text']}
        },
        {
            'name': 'y1',
            'label': 'Y1 / Center Y',
            'type': 'number',
            'default': DEFAULT_CONFIG['y1'],
            'help': 'Y coordinate (start point or center)',
            'showIf': {'shape': ['rectangle', 'circle', 'line', 'text']}
        },
        {
            'name': 'x2',
            'label': 'X2 / Width',
            'type': 'number',
            'default': DEFAULT_CONFIG['x2'],
            'help': 'X2 for line/rect, or width',
            'showIf': {'shape': ['rectangle', 'line']}
        },
        {
            'name': 'y2',
            'label': 'Y2 / Height',
            'type': 'number',
            'default': DEFAULT_CONFIG['y2'],
            'help': 'Y2 for line/rect, or height',
            'showIf': {'shape': ['rectangle', 'line']}
        },
        {
            'name': 'radius',
            'label': 'Radius',
            'type': 'number',
            'default': DEFAULT_CONFIG['radius'],
            'help': 'Circle radius',
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
            'x1': 100,
            'y1': 100,
            'x2': 200,
            'y2': 200,
            'radius': 50,
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
        """Draw a single shape on the image."""
        shape_type = shape_info.get('type', 'rectangle')
        color = self._parse_color(shape_info.get('color', '0,255,0'))
        thickness = int(shape_info.get('thickness', 2))
        
        if shape_type == 'rectangle':
            x1 = int(shape_info.get('x1', 0))
            y1 = int(shape_info.get('y1', 0))
            x2 = int(shape_info.get('x2', 100))
            y2 = int(shape_info.get('y2', 100))
            cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
        
        elif shape_type == 'circle':
            cx = int(shape_info.get('x1', shape_info.get('cx', 100)))
            cy = int(shape_info.get('y1', shape_info.get('cy', 100)))
            radius = int(shape_info.get('radius', 50))
            cv2.circle(img, (cx, cy), radius, color, thickness)
        
        elif shape_type == 'line':
            x1 = int(shape_info.get('x1', 0))
            y1 = int(shape_info.get('y1', 0))
            x2 = int(shape_info.get('x2', 100))
            y2 = int(shape_info.get('y2', 100))
            cv2.line(img, (x1, y1), (x2, y2), color, thickness)
        
        elif shape_type == 'text':
            x = int(shape_info.get('x1', shape_info.get('x', 100)))
            y = int(shape_info.get('y1', shape_info.get('y', 100)))
            text = str(shape_info.get('text', ''))
            font_scale = float(shape_info.get('font_scale', 1.0))
            cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 
                       font_scale, color, thickness)
        
        return img
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Draw shapes on the input image."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        # Make a copy to draw on
        result = img.copy()
        
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
                'x1': self.config.get('x1', 100),
                'y1': self.config.get('y1', 100),
                'x2': self.config.get('x2', 200),
                'y2': self.config.get('y2', 200),
                'radius': self.config.get('radius', 50),
                'color': self.config.get('color', '0,255,0'),
                'thickness': self.config.get('thickness', 2),
                'text': self.config.get('text', 'Hello'),
                'font_scale': self.config.get('font_scale', 1.0)
            }
            result = self._draw_shape(result, shape_info)
        
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(result, format_type)
        self.send(msg)
