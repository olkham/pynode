"""
BBoxMetricsNode - Calculate metrics from bounding boxes

This node calculates various metrics from bounding box predictions including:
- Width and height
- Area
- Aspect ratio
- Center point coordinates
- Diagonal length

Input format:
    msg['detections'] - List of detections with bounding boxes
    OR
    msg['boxes'] - Array of bounding boxes [x1, y1, x2, y2]
    OR
    msg['bbox'] - Single bounding box [x1, y1, x2, y2]

Output format:
    msg['metrics'] - Dictionary containing calculated metrics
    msg['detections'] - Original detections with added 'metrics' field
"""

import sys
import os
from typing import Any, Dict
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from pynode.nodes.base_node import BaseNode, Info
import numpy as np

_info = Info()
_info.add_text("Calculates geometric metrics from bounding boxes including dimensions, area, aspect ratio, center point, and diagonal length.")
_info.add_header("Input")
_info.add_bullets(
    ("detections:", "List of detection objects containing 'bbox' field."),
    ("boxes:", "Array of bounding boxes [x1, y1, x2, y2]."),
    ("bbox:", "Single bounding box [x1, y1, x2, y2]."),
)
_info.add_header("Output")
_info.add_bullets(
    ("metrics:", "Calculated metrics (width, height, area, aspect_ratio, center, diagonal)."),
    ("detections:", "Original detections with 'metrics' field added to each."),
)
_info.add_header("Properties")
_info.add_bullets(
    ("Metrics to Calculate:", "Select which metrics to compute."),
    ("Normalize:", "Normalize values by image dimensions."),
    ("Image Dimensions:", "Reference size for normalization."),
)


class BBoxMetricsNode(BaseNode):
    """Calculate metrics from bounding boxes"""
    info = str(_info)
    display_name = 'BBox Metrics'
    icon = '📏'
    category = 'analysis'
    color = '#FFE5B4'
    border_color = '#D4AF37'
    text_color = '#000000'
    
    DEFAULT_CONFIG = {
        'metrics': ['width', 'height', 'area', 'aspect_ratio', 'center', 'diagonal'],
        'normalize': False,
        'use_image_dimensions': False,
        'image_width': 1920,
        'image_height': 1080
    }
    
    properties = [
        {
            'name': 'metrics',
            'label': 'Metrics to Calculate',
            'type': 'multiselect',
            'options': ['width', 'height', 'area', 'aspect_ratio', 'center', 'diagonal'],
            'default': DEFAULT_CONFIG['metrics']
        },
        {
            'name': 'normalize',
            'label': 'Normalize by Image Size',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['normalize']
        },
        {
            'name': 'use_image_dimensions',
            'label': 'Use Image Dimensions from Message',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['use_image_dimensions']
        },
        {
            'name': 'image_width',
            'label': 'Reference Image Width',
            'type': 'number',
            'default': DEFAULT_CONFIG['image_width'],
            'showIf': {'use_image_dimensions': False}
        },
        {
            'name': 'image_height',
            'label': 'Reference Image Height',
            'type': 'number',
            'default': DEFAULT_CONFIG['image_height'],
            'showIf': {'use_image_dimensions': False}
        }
    ]
    
    def __init__(self, node_id=None, name="BBox Metrics"):
        super().__init__(node_id, name)
    
    def _calculate_bbox_metrics(self, bbox, normalize=False, img_w=1920, img_h=1080, bbox_format='xyxy'):
        """
        Calculate metrics for a single bounding box
        
        Args:
            bbox: Bounding box in specified format
            normalize: Whether to normalize metrics by image dimensions
            img_w: Image width for normalization
            img_h: Image height for normalization
            bbox_format: Format of bbox - 'xyxy' [x1,y1,x2,y2], 'xywh' [x,y,w,h], 'cxcywh' [cx,cy,w,h]
        
        Returns:
            Dictionary of metrics
        """
        # Convert bbox to xyxy format for consistent processing
        if bbox_format == 'xyxy':
            x1, y1, x2, y2 = bbox[:4]
        elif bbox_format == 'xywh':
            x, y, w, h = bbox[:4]
            x1, y1, x2, y2 = x, y, x + w, y + h
        elif bbox_format == 'cxcywh':
            cx, cy, w, h = bbox[:4]
            x1 = cx - w / 2
            y1 = cy - h / 2
            x2 = cx + w / 2
            y2 = cy + h / 2
        else:
            # Default to xyxy if unknown format
            x1, y1, x2, y2 = bbox[:4]
        
        # Basic dimensions
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        area = width * height
        
        # Center point
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        
        # Aspect ratio (width/height)
        aspect_ratio = width / height if height > 0 else 0
        
        # Diagonal length
        diagonal = np.sqrt(width**2 + height**2)
        
        metrics = {
            'width': width,
            'height': height,
            'area': area,
            'aspect_ratio': aspect_ratio,
            'center': {'x': center_x, 'y': center_y},
            'diagonal': diagonal,
            'bbox': [x1, y1, x2, y2],
            'bbox_format': 'xyxy'  # Output is always normalized to xyxy
        }
        
        # Normalize if requested
        if normalize:
            metrics['width_normalized'] = width / img_w
            metrics['height_normalized'] = height / img_h
            metrics['area_normalized'] = area / (img_w * img_h)
            metrics['center_normalized'] = [center_x / img_w, center_y / img_h]
            metrics['diagonal_normalized'] = diagonal / np.sqrt(img_w**2 + img_h**2)
        
        # Filter to only requested metrics
        selected_metrics = self.config.get('metrics', [])
        if selected_metrics:
            filtered = {k: v for k, v in metrics.items() if k in selected_metrics or k == 'bbox'}
            # Always include normalized versions if normalize is enabled
            if normalize:
                for key in list(filtered.keys()):
                    norm_key = f"{key}_normalized"
                    if norm_key in metrics:
                        filtered[norm_key] = metrics[norm_key]
            return filtered
        
        return metrics
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Calculate bounding box metrics"""
        try:
            normalize = self.config.get('normalize', False)
            use_image_dimensions = self.config.get('use_image_dimensions', True)
            img_w = self.get_config_int('image_width', 1920)
            img_h = self.get_config_int('image_height', 1080)
            
            # Check both top level and payload for data
            data_source = msg.get('payload', msg)
            
            # Get bbox format from message (default to xyxy)
            bbox_format = data_source.get('bbox_format', 'xyxy')
            
            # Try to get image dimensions from message if enabled
            if use_image_dimensions:
                if 'image' in data_source and hasattr(data_source['image'], 'shape'):
                    img_h, img_w = data_source['image'].shape[:2]
                elif 'image' in data_source and isinstance(data_source['image'], dict):
                    # Handle nested image structure
                    img_w = data_source['image'].get('width', img_w)
                    img_h = data_source['image'].get('height', img_h)
                elif 'image_width' in data_source:
                    img_w = data_source['image_width']
                    img_h = data_source.get('image_height', img_h)
            
            # Process detections with bounding boxes
            if 'detections' in data_source:
                detections = data_source['detections']
                if isinstance(detections, list):
                    for det in detections:
                        if 'bbox' in det or 'box' in det:
                            bbox = det.get('bbox', det.get('box'))
                            # Check for detection-specific bbox_format, fallback to message-level
                            det_bbox_format = det.get('bbox_format', bbox_format)
                            det['metrics'] = self._calculate_bbox_metrics(bbox, normalize, img_w, img_h, det_bbox_format)
                    data_source['detections'] = detections
                    self.send(msg)
            
            # Process array of boxes
            elif 'boxes' in data_source:
                boxes = data_source['boxes']
                if isinstance(boxes, (list, np.ndarray)):
                    metrics_list = []
                    for bbox in boxes:
                        metrics = self._calculate_bbox_metrics(bbox, normalize, img_w, img_h, bbox_format)
                        metrics_list.append(metrics)
                    data_source['metrics'] = metrics_list
                    self.send(msg)
            
            # Process single bbox
            elif 'bbox' in data_source:
                bbox = data_source['bbox']
                metrics = self._calculate_bbox_metrics(bbox, normalize, img_w, img_h, bbox_format)
                data_source['metrics'] = metrics
                self.send(msg)
            
            else:
                self.report_error(f"No bounding boxes found in message. Expected 'detections', 'boxes', or 'bbox' field.")
                
        except Exception as e:
            self.report_error(f"Error calculating bbox metrics: {str(e)}")
            import traceback
            self.report_error(traceback.format_exc())
