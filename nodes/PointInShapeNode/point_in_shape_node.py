"""
PointInShapeNode - Check if points are inside shapes

This node checks if points/coordinates are inside rectangles or polygons.
Useful for:
- Region of interest filtering
- Zone detection
- Spatial filtering of detections
- Click/touch detection in shapes

Input format:
    msg['point'] - Single point [x, y]
    OR
    msg['points'] - List of points [[x1, y1], [x2, y2], ...]
    
    AND one of:
    msg['rect'] - Rectangle [x1, y1, x2, y2]
    msg['polygon'] - Polygon [[x1, y1], [x2, y2], ...]
    msg['detections'] - Detections with bbox/polygon to check against

Output format:
    msg['inside'] - Boolean or list of booleans
    msg['filtered_points'] - Points that are inside (if filtering enabled)
    msg['filtered_detections'] - Detections that contain the point(s)
"""

import sys
import os
from typing import Any, Dict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from nodes.base_node import BaseNode
import numpy as np
import cv2


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
        'filter_mode': False,
        'check_type': 'any'
    }
    
    properties = [
        {
            'name': 'filter_mode',
            'label': 'Filter Mode (only pass matching)',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['filter_mode']
        },
        {
            'name': 'check_type',
            'label': 'Check Type (for multiple points)',
            'type': 'select',
            'options': ['any', 'all'],
            'default': DEFAULT_CONFIG['check_type']
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
    
    def _check_point_in_shape(self, point, shape_type, shape_data):
        """
        Check if point is in shape
        
        Args:
            point: [x, y]
            shape_type: 'rect' or 'polygon'
            shape_data: Rectangle or polygon data
        
        Returns:
            Boolean
        """
        if shape_type == 'rect':
            return self._point_in_rect(point, shape_data)
        elif shape_type == 'polygon':
            return self._point_in_polygon(point, shape_data)
        else:
            return False
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Check if points are inside shapes"""
        try:
            filter_mode = self.config.get('filter_mode', False)
            check_type = self.config.get('check_type', 'any')
            
            # Check both top level and payload for data
            data_source = msg.get('payload', msg)
            
            # Determine shape type and data
            shape_type = None
            shape_data = None
            
            if 'rect' in data_source or 'bbox' in data_source:
                shape_type = 'rect'
                shape_data = data_source.get('rect', data_source.get('bbox'))
            elif 'polygon' in data_source:
                shape_type = 'polygon'
                shape_data = data_source['polygon']
            
            # Check single point
            if 'point' in data_source:
                point = data_source['point']
                
                if shape_type and shape_data:
                    # Check against provided shape
                    inside = self._check_point_in_shape(point, shape_type, shape_data)
                    data_source['inside'] = inside
                    
                    if not filter_mode or inside:
                        self.send(msg)
                
                elif 'detections' in data_source:
                    # Check against all detections
                    filtered_detections = []
                    inside_list = []
                    
                    for det in data_source['detections']:
                        inside = False
                        
                        if 'bbox' in det or 'box' in det:
                            bbox = det.get('bbox', det.get('box'))
                            inside = self._point_in_rect(point, bbox)
                        elif 'polygon' in det:
                            inside = self._point_in_polygon(point, det['polygon'])
                        
                        inside_list.append(inside)
                        if inside:
                            filtered_detections.append(det)
                    
                    data_source['inside'] = inside_list
                    data_source['filtered_detections'] = filtered_detections
                    data_source['any_inside'] = any(inside_list)
                    data_source['all_inside'] = all(inside_list)
                    
                    self.send(msg)
            
            # Check multiple points
            elif 'points' in data_source:
                points = data_source['points']
                
                if shape_type and shape_data:
                    # Check all points against provided shape
                    inside_list = []
                    filtered_points = []
                    
                    for point in points:
                        inside = self._check_point_in_shape(point, shape_type, shape_data)
                        inside_list.append(inside)
                        if inside:
                            filtered_points.append(point)
                    
                    data_source['inside'] = inside_list
                    data_source['filtered_points'] = filtered_points
                    data_source['any_inside'] = any(inside_list)
                    data_source['all_inside'] = all(inside_list)
                    
                    if not filter_mode or (check_type == 'any' and data_source['any_inside']) or (check_type == 'all' and data_source['all_inside']):
                        self.send(msg)
                
                elif 'detections' in data_source:
                    # For each detection, check which points are inside
                    for det in data_source['detections']:
                        inside_list = []
                        
                        if 'bbox' in det or 'box' in det:
                            bbox = det.get('bbox', det.get('box'))
                            for point in points:
                                inside_list.append(self._point_in_rect(point, bbox))
                        elif 'polygon' in det:
                            for point in points:
                                inside_list.append(self._point_in_polygon(point, det['polygon']))
                        
                        det['points_inside'] = inside_list
                        det['num_points_inside'] = sum(inside_list)
                        det['any_points_inside'] = any(inside_list)
                        det['all_points_inside'] = all(inside_list)
                    
                    # Filter detections if requested
                    if filter_mode:
                        if check_type == 'any':
                            data_source['detections'] = [d for d in data_source['detections'] if d.get('any_points_inside', False)]
                        else:  # 'all'
                            data_source['detections'] = [d for d in data_source['detections'] if d.get('all_points_inside', False)]
                    
                    self.send(msg)
            
            # Check detections against a reference shape
            elif 'detections' in data_source and shape_type and shape_data:
                filtered_detections = []
                
                for det in data_source['detections']:
                    # Get center point of detection
                    center = None
                    
                    if 'bbox' in det or 'box' in det:
                        bbox = det.get('bbox', det.get('box'))
                        center = [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]
                    elif 'polygon' in det:
                        polygon = np.array(det['polygon'])
                        center = [float(np.mean(polygon[:, 0])), float(np.mean(polygon[:, 1]))]
                    
                    if center:
                        inside = self._check_point_in_shape(center, shape_type, shape_data)
                        det['center_inside'] = inside
                        
                        if inside:
                            filtered_detections.append(det)
                
                if filter_mode:
                    data_source['detections'] = filtered_detections
                else:
                    data_source['filtered_detections'] = filtered_detections
                
                self.send(msg)
            
            else:
                self.report_error("No valid point/shape combination found in message")
                
        except Exception as e:
            self.report_error(f"Error checking point in shape: {str(e)}")
            import traceback
            self.report_error(traceback.format_exc())
