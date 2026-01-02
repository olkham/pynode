"""
PolygonMetricsNode - Calculate metrics from polygons

This node calculates various metrics from polygon predictions including:
- Polygon area
- Bounding box (width, height, area)
- Maximum internal rectangle
- Minimum external rectangle
- Perimeter
- Centroid

Input format:
    msg['detections'] - List of detections with polygons
    OR
    msg['polygons'] - List of polygons (array of points)
    OR
    msg['polygon'] - Single polygon (array of points [[x1,y1], [x2,y2], ...])

Output format:
    msg['metrics'] - Dictionary containing calculated metrics
    msg['detections'] - Original detections with added 'metrics' field
"""

import sys
import os
from typing import Any, Dict
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from pynode.nodes.base_node import BaseNode
import numpy as np
import cv2


class PolygonMetricsNode(BaseNode):
    """Calculate metrics from polygons"""
    
    info = str(_info)
    display_name = 'Polygon Metrics'
    icon = '⬡'
    category = 'analysis'
    color = '#E6E6FA'
    border_color = '#9370DB'
    text_color = '#000000'
    
    DEFAULT_CONFIG = {
        'metrics': ['area', 'perimeter', 'bbox', 'centroid', 'max_internal_rect', 'min_external_rect'],
        'normalize': False,
        'image_width': 1920,
        'image_height': 1080
    }
    
    properties = [
        {
            'name': 'metrics',
            'label': 'Metrics to Calculate',
            'type': 'multiselect',
            'options': ['area', 'perimeter', 'bbox', 'centroid', 'max_internal_rect', 'min_external_rect'],
            'default': DEFAULT_CONFIG['metrics']
        },
        {
            'name': 'normalize',
            'label': 'Normalize by Image Size',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['normalize']
        },
        {
            'name': 'image_width',
            'label': 'Image Width (for normalization)',
            'type': 'number',
            'default': DEFAULT_CONFIG['image_width']
        },
        {
            'name': 'image_height',
            'label': 'Image Height (for normalization)',
            'type': 'number',
            'default': DEFAULT_CONFIG['image_height']
        }
    ]
    
    def __init__(self, node_id=None, name="Polygon Metrics"):
        super().__init__(node_id, name)
    
    def _polygon_area(self, points):
        """Calculate polygon area using shoelace formula"""
        if len(points) < 3:
            return 0.0
        
        points = np.array(points)
        x = points[:, 0]
        y = points[:, 1]
        return 0.5 * np.abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))
    
    def _polygon_perimeter(self, points):
        """Calculate polygon perimeter"""
        if len(points) < 2:
            return 0.0
        
        points = np.array(points)
        # Calculate distance between consecutive points
        diffs = np.diff(points, axis=0, append=[points[0]])
        distances = np.sqrt(np.sum(diffs**2, axis=1))
        return np.sum(distances)
    
    def _polygon_centroid(self, points):
        """Calculate polygon centroid"""
        if len(points) < 3:
            return [0.0, 0.0]
        
        points = np.array(points)
        M = cv2.moments(points.astype(np.float32))
        
        if M['m00'] != 0:
            cx = M['m10'] / M['m00']
            cy = M['m01'] / M['m00']
            return [float(cx), float(cy)]
        else:
            # Fallback to simple average
            return [float(np.mean(points[:, 0])), float(np.mean(points[:, 1]))]
    
    def _polygon_bounding_box(self, points):
        """Get bounding box of polygon"""
        if len(points) < 1:
            return [0, 0, 0, 0]
        
        points = np.array(points)
        x_min = np.min(points[:, 0])
        y_min = np.min(points[:, 1])
        x_max = np.max(points[:, 0])
        y_max = np.max(points[:, 1])
        
        return [float(x_min), float(y_min), float(x_max), float(y_max)]
    
    def _minimum_external_rect(self, points):
        """Calculate minimum area rectangle that contains the polygon"""
        if len(points) < 3:
            return None
        
        points = np.array(points, dtype=np.float32)
        rect = cv2.minAreaRect(points)
        box = cv2.boxPoints(rect)
        
        # rect is ((center_x, center_y), (width, height), angle)
        center, size, angle = rect
        width, height = size
        
        return {
            'center': [float(center[0]), float(center[1])],
            'width': float(width),
            'height': float(height),
            'area': float(width * height),
            'angle': float(angle),
            'corners': box.tolist()
        }
    
    def _maximum_internal_rect(self, points, image_width=1920, image_height=1080):
        """
        Estimate maximum inscribed rectangle.
        This is a simplified approximation using the bounding box approach.
        For more accurate results, more complex algorithms would be needed.
        """
        if len(points) < 3:
            return None
        
        # Get bounding box as approximation
        bbox = self._polygon_bounding_box(points)
        x1, y1, x2, y2 = bbox
        width = x2 - x1
        height = y2 - y1
        
        # For convex polygons, we could do better, but this is a reasonable approximation
        # Scale down by a factor to ensure it fits inside
        scale_factor = 0.9
        scaled_width = width * scale_factor
        scaled_height = height * scale_factor
        
        center = [(x1 + x2) / 2, (y1 + y2) / 2]
        
        return {
            'center': center,
            'width': float(scaled_width),
            'height': float(scaled_height),
            'area': float(scaled_width * scaled_height),
            'bbox': [
                center[0] - scaled_width/2,
                center[1] - scaled_height/2,
                center[0] + scaled_width/2,
                center[1] + scaled_height/2
            ]
        }
    
    def _calculate_polygon_metrics(self, polygon, normalize=False, img_w=1920, img_h=1080):
        """
        Calculate metrics for a single polygon
        
        Args:
            polygon: List of points [[x1, y1], [x2, y2], ...]
            normalize: Whether to normalize metrics by image dimensions
            img_w: Image width for normalization
            img_h: Image height for normalization
        
        Returns:
            Dictionary of metrics
        """
        if isinstance(polygon, np.ndarray):
            if polygon.ndim == 1:
                # Reshape flat array to points
                polygon = polygon.reshape(-1, 2)
            polygon = polygon.tolist()
        
        # Calculate all metrics
        area = self._polygon_area(polygon)
        perimeter = self._polygon_perimeter(polygon)
        centroid = self._polygon_centroid(polygon)
        bbox = self._polygon_bounding_box(polygon)
        min_rect = self._minimum_external_rect(polygon)
        max_rect = self._maximum_internal_rect(polygon, img_w, img_h)
        
        bbox_width = bbox[2] - bbox[0]
        bbox_height = bbox[3] - bbox[1]
        bbox_area = bbox_width * bbox_height
        
        metrics = {
            'area': float(area),
            'perimeter': float(perimeter),
            'centroid': centroid,
            'bbox': bbox,
            'bbox_width': float(bbox_width),
            'bbox_height': float(bbox_height),
            'bbox_area': float(bbox_area),
            'min_external_rect': min_rect,
            'max_internal_rect': max_rect,
            'num_points': len(polygon)
        }
        
        # Normalize if requested
        if normalize:
            metrics['area_normalized'] = area / (img_w * img_h)
            metrics['perimeter_normalized'] = perimeter / (img_w + img_h)
            metrics['centroid_normalized'] = [centroid[0] / img_w, centroid[1] / img_h]
            metrics['bbox_width_normalized'] = bbox_width / img_w
            metrics['bbox_height_normalized'] = bbox_height / img_h
            metrics['bbox_area_normalized'] = bbox_area / (img_w * img_h)
        
        # Filter to only requested metrics
        selected_metrics = self.config.get('metrics', [])
        if selected_metrics and isinstance(selected_metrics, list):
            filtered = {k: v for k, v in metrics.items() 
                       if any(sel in k for sel in selected_metrics) or k == 'num_points'}
            return filtered
        
        return metrics
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Calculate polygon metrics"""
        try:
            normalize = self.config.get('normalize', False)
            img_w = self.get_config_int('image_width', 1920)
            img_h = self.get_config_int('image_height', 1080)
            
            # Check both top level and payload for data
            data_source = msg.get('payload', msg)
            
            # Try to get image dimensions from message
            if 'image' in data_source and hasattr(data_source['image'], 'shape'):
                img_h, img_w = data_source['image'].shape[:2]
            elif 'image' in data_source and isinstance(data_source['image'], dict):
                img_w = data_source['image'].get('width', img_w)
                img_h = data_source['image'].get('height', img_h)
            elif 'image_width' in data_source:
                img_w = data_source['image_width']
                img_h = data_source.get('image_height', img_h)
            
            # Process detections with polygons
            if 'detections' in data_source:
                detections = data_source['detections']
                if isinstance(detections, list):
                    for det in detections:
                        # Look for polygon data in various formats
                        polygon = None
                        if 'polygon' in det:
                            polygon = det['polygon']
                        elif 'segmentation' in det:
                            polygon = det['segmentation']
                        elif 'mask' in det and isinstance(det['mask'], list):
                            polygon = det['mask']
                        
                        if polygon is not None:
                            det['metrics'] = self._calculate_polygon_metrics(polygon, normalize, img_w, img_h)
                    
                    data_source['detections'] = detections
                    self.send(msg)
            
            # Process array of polygons
            elif 'polygons' in data_source:
                polygons = data_source['polygons']
                if isinstance(polygons, list):
                    metrics_list = []
                    for polygon in polygons:
                        metrics = self._calculate_polygon_metrics(polygon, normalize, img_w, img_h)
                        metrics_list.append(metrics)
                    data_source['metrics'] = metrics_list
                    self.send(msg)
            
            # Process single polygon
            elif 'polygon' in data_source:
                polygon = data_source['polygon']
                metrics = self._calculate_polygon_metrics(polygon, normalize, img_w, img_h)
                data_source['metrics'] = metrics
                self.send(msg)
            
            else:
                self.report_error(f"No polygons found in message. Expected 'detections', 'polygons', or 'polygon' field.")
                
        except Exception as e:
            self.report_error(f"Error calculating polygon metrics: {str(e)}")
            import traceback
            self.report_error(traceback.format_exc())
