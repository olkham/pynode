"""
PointInShapeNode - Check if a point is inside a shape

This node tests whether a point (x, y coordinate) is inside a shape.
Supported shapes: rectangle, polygon, circle

Shapes can be:
- Manually defined in node properties
- Read from the incoming message

Useful for:
- Region of interest detection
- Zone/boundary testing
- Spatial filtering
- Click/touch detection in UI regions
"""

import sys
import os
import json
from typing import Any, Dict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from pynode.nodes.base_node import BaseNode, Info
import numpy as np
import cv2

_info = Info()
_info.add_text("Check if a point is inside a shape (rectangle, polygon, or circle).")
_info.add_header("Configuration")
_info.add_bullets(
    ("Shape Source:", "Manual (define in properties) or From Message (read from msg)"),
    ("Shape Type:", "Rectangle, Polygon, or Circle"),
    ("Point Path:", "Path to point in message (e.g., 'payload.point' or 'click')"),
    ("Shape Path:", "Path to shape in message (when using From Message)")
)
_info.add_header("Input")
_info.add_bullets(
    ("Point:", "Point coordinates [x, y] at configured path"),
    ("Shape:", "Shape data at configured path (when using From Message)")
)
_info.add_header("Output")
_info.add_bullets(
    ("payload.inside:", "Boolean - true if point is inside shape"),
    ("payload.point:", "The tested point [x, y]"),
    ("payload.shape_type:", "Type of shape tested against")
)


class PointInShapeNode(BaseNode):
    """Check if points are inside shapes"""
    
    info = str(_info)
    display_name = 'Point in Shape'
    icon = '📍'
    category = 'analysis'
    color = '#FFE4E1'
    border_color = '#DC143C'
    text_color = '#000000'
    
    DEFAULT_CONFIG = {
        'point_path': 'payload.point',
        'shape_source': 'manual',
        'shape_type': 'rect',
        'shape_path': 'payload.shape',
        'rect': '100,100,300,300',
        'polygon': '[[100,100],[300,100],[300,300],[100,300]]',
        'circle': '200,200,100'
    }
    
    properties = [
        {
            'name': 'point_path',
            'label': 'Point Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['point_path'],
            'help': 'Path to point in message (e.g., "payload.point", "click")'
        },
        {
            'name': 'shape_source',
            'label': 'Shape Source',
            'type': 'select',
            'options': [
                {'value': 'manual', 'label': 'Manual (define below)'},
                {'value': 'message', 'label': 'From Message'}
            ],
            'default': DEFAULT_CONFIG['shape_source']
        },
        {
            'name': 'shape_type',
            'label': 'Shape Type',
            'type': 'select',
            'options': [
                {'value': 'rect', 'label': 'Rectangle'},
                {'value': 'polygon', 'label': 'Polygon'},
                {'value': 'circle', 'label': 'Circle'}
            ],
            'default': DEFAULT_CONFIG['shape_type'],
            'showIf': {'shape_source': 'manual'}
        },
        {
            'name': 'shape_path',
            'label': 'Shape Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['shape_path'],
            'help': 'Path to shape in message',
            'showIf': {'shape_source': 'message'}
        },
        {
            'name': 'rect',
            'label': 'Rectangle (x1,y1,x2,y2)',
            'type': 'text',
            'default': DEFAULT_CONFIG['rect'],
            'help': 'Format: x1,y1,x2,y2',
            'showIf': {'shape_source': 'manual', 'shape_type': 'rect'}
        },
        {
            'name': 'polygon',
            'label': 'Polygon Points',
            'type': 'text',
            'default': DEFAULT_CONFIG['polygon'],
            'help': 'Format: [[x1,y1],[x2,y2],[x3,y3],...]',
            'showIf': {'shape_source': 'manual', 'shape_type': 'polygon'}
        },
        {
            'name': 'circle',
            'label': 'Circle (x,y,radius)',
            'type': 'text',
            'default': DEFAULT_CONFIG['circle'],
            'help': 'Format: center_x,center_y,radius',
            'showIf': {'shape_source': 'manual', 'shape_type': 'circle'}
        }
    ]
    
    def __init__(self, node_id=None, name="Point in Shape"):
        super().__init__(node_id, name)
    
    def _point_in_rect(self, point, rect):
        """
        Check if a point is inside a rectangle
        
        Args:
            point: [x, y]
            rect: [x1, y1, x2, y2]
        
        Returns:
            Boolean
        """
        x, y = point
        x1, y1, x2, y2 = rect
        
        # Ensure correct order
        x_min = min(x1, x2)
        x_max = max(x1, x2)
        y_min = min(y1, y2)
        y_max = max(y1, y2)
        
        return x_min <= x <= x_max and y_min <= y <= y_max
    
    def _point_in_polygon(self, point, polygon):
        """
        Check if a point is inside a polygon
        
        Args:
            point: [x, y]
            polygon: [[x1, y1], [x2, y2], ...]
        
        Returns:
            Boolean
        """
        if isinstance(polygon, list):
            polygon = np.array(polygon, dtype=np.float32)
        
        if len(polygon) < 3:
            return False
        
        # Use OpenCV's pointPolygonTest
        # Returns: positive (inside), negative (outside), or zero (on edge)
        result = cv2.pointPolygonTest(polygon, (float(point[0]), float(point[1])), False)
        return result >= 0
    
    def _point_in_circle(self, point, circle):
        """
        Check if a point is inside a circle
        
        Args:
            point: [x, y]
            circle: [center_x, center_y, radius]
        
        Returns:
            Boolean
        """
        x, y = point
        cx, cy, radius = circle
        
        # Calculate distance from center
        distance = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        
        return distance <= radius
    
    def _get_nested_value(self, obj, path):
        """
        Get a value from a nested path like 'payload.point' or 'click'
        
        Args:
            obj: The object to get value from
            path: Dot-separated path string
        
        Returns:
            The value at the path, or None if not found
        """
        if not path:
            return None
            
        parts = path.split('.')
        current = obj
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        return current
    
    def _parse_manual_shape(self, shape_type, shape_str):
        """
        Parse manually configured shape from string
        
        Args:
            shape_type: 'rect', 'polygon', or 'circle'
            shape_str: String representation of the shape
        
        Returns:
            Parsed shape data
        """
        try:
            if shape_type == 'rect':
                # Format: "x1,y1,x2,y2"
                parts = [float(x.strip()) for x in shape_str.split(',')]
                if len(parts) == 4:
                    return parts
            
            elif shape_type == 'polygon':
                # Format: "[[x1,y1],[x2,y2],...]"
                return json.loads(shape_str)
            
            elif shape_type == 'circle':
                # Format: "cx,cy,radius"
                parts = [float(x.strip()) for x in shape_str.split(',')]
                if len(parts) == 3:
                    return parts
        
        except Exception as e:
            self.report_error(f"Error parsing shape: {str(e)}")
        
        return None
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Check if a point is inside a shape"""
        try:
            # Get configuration
            point_path = self.config.get('point_path', 'payload.point')
            shape_source = self.config.get('shape_source', 'manual')
            shape_type = self.config.get('shape_type', 'rect')
            
            # Get the point from the message
            point = self._get_nested_value(msg, point_path)
            
            if point is None:
                self.report_error(f"Point not found at path: {point_path}")
                return
            
            # Validate point format
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                self.report_error(f"Point must be [x, y], got: {point}")
                return
            
            # Get the shape
            shape_data = None
            
            if shape_source == 'manual':
                # Parse manually configured shape
                shape_str = self.config.get(shape_type, '')
                shape_data = self._parse_manual_shape(shape_type, shape_str)
                
                if shape_data is None:
                    self.report_error(f"Invalid {shape_type} configuration: {shape_str}")
                    return
            
            else:  # from message
                shape_path = self.config.get('shape_path', 'payload.shape')
                shape_data = self._get_nested_value(msg, shape_path)
                
                if shape_data is None:
                    self.report_error(f"Shape not found at path: {shape_path}")
                    return
                
                # Try to determine shape type from data if it's a dict with type info
                if isinstance(shape_data, dict):
                    if 'rect' in shape_data or 'bbox' in shape_data:
                        shape_type = 'rect'
                        shape_data = shape_data.get('rect', shape_data.get('bbox'))
                    elif 'polygon' in shape_data:
                        shape_type = 'polygon'
                        shape_data = shape_data['polygon']
                    elif 'circle' in shape_data:
                        shape_type = 'circle'
                        shape_data = shape_data['circle']
            
            # Test the point against the shape
            inside = False
            
            if shape_type == 'rect':
                inside = self._point_in_rect(point, shape_data)
            elif shape_type == 'polygon':
                inside = self._point_in_polygon(point, shape_data)
            elif shape_type == 'circle':
                inside = self._point_in_circle(point, shape_data)
            else:
                self.report_error(f"Unknown shape type: {shape_type}")
                return
            
            # Create output
            if 'payload' not in msg:
                msg['payload'] = {}
            
            msg['payload']['inside'] = inside
            msg['payload']['point'] = list(point)
            msg['payload']['shape_type'] = shape_type
            
            self.send(msg)
                
        except Exception as e:
            self.report_error(f"Error checking point in shape: {str(e)}")
            import traceback
            self.report_error(traceback.format_exc())
