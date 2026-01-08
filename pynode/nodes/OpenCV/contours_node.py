"""
OpenCV Contours Node - finds contours in binary images.
Detects and analyzes contours for shape detection.
"""

import cv2
import numpy as np
from typing import Any, Dict, List
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Finds and analyzes contours in binary/edge images. Outputs contour data including area, perimeter, bounding boxes, and centroids.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Binary or edge-detected image (grayscale recommended)"))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Image with contours drawn (if enabled)"),
    ("msg.contours:", "List of contour data with normalized coordinates (0.0-1.0)")
)
_info.add_header("Normalized Coordinates")
_info.add_text("All coordinates and areas are normalized for resolution independence.")
_info.add_header("Properties")
_info.add_bullets(
    ("Retrieval Mode:", "External only, All (list), All (hierarchy), or Two-level"),
    ("Approximation:", "Contour point approximation method"),
    ("Min/Max Area:", "Filter contours by area (normalized 0.0-1.0)")
)


class ContoursNode(BaseNode):
    info = str(_info)
    """
    Contours node - finds and analyzes contours in binary images.
    Outputs contour data including area, perimeter, bounding boxes, and centroids.
    """
    display_name = 'Find Contours'
    icon = '▢'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'mode': 'external',
        'approximation': 'simple',
        'min_area': 0.001,
        'max_area': 0.0,
        'draw_contours': 'yes',
        'draw_bboxes': 'no'
    }
    
    properties = [
        {
            'name': 'mode',
            'label': 'Retrieval Mode',
            'type': 'select',
            'options': [
                {'value': 'external', 'label': 'External only'},
                {'value': 'list', 'label': 'All (list)'},
                {'value': 'tree', 'label': 'All (hierarchy)'},
                {'value': 'ccomp', 'label': 'Two-level hierarchy'}
            ],
            'default': DEFAULT_CONFIG['mode'],
            'help': 'How to retrieve contours'
        },
        {
            'name': 'approximation',
            'label': 'Approximation',
            'type': 'select',
            'options': [
                {'value': 'none', 'label': 'None (all points)'},
                {'value': 'simple', 'label': 'Simple'},
                {'value': 'tc89_l1', 'label': 'Teh-Chin L1'},
                {'value': 'tc89_kcos', 'label': 'Teh-Chin KCOS'}
            ],
            'default': DEFAULT_CONFIG['approximation'],
            'help': 'Contour approximation method'
        },
        {
            'name': 'min_area',
            'label': 'Min Area',
            'type': 'number',
            'default': DEFAULT_CONFIG['min_area'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.001,
            'help': 'Minimum contour area (normalized 0.0-1.0)'
        },
        {
            'name': 'max_area',
            'label': 'Max Area',
            'type': 'number',
            'default': DEFAULT_CONFIG['max_area'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.001,
            'help': 'Maximum contour area (normalized 0.0-1.0, 0 = no limit)'
        },
        {
            'name': 'draw_contours',
            'label': 'Draw Contours',
            'type': 'select',
            'options': [
                {'value': 'yes', 'label': 'Yes'},
                {'value': 'no', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['draw_contours'],
            'help': 'Draw detected contours on output image'
        },
        {
            'name': 'draw_bboxes',
            'label': 'Draw Bounding Boxes',
            'type': 'select',
            'options': [
                {'value': 'yes', 'label': 'Yes'},
                {'value': 'no', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['draw_bboxes'],
            'help': 'Draw bounding boxes around contours'
        }
    ]
    
    def __init__(self, node_id=None, name="find contours"):
        super().__init__(node_id, name)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Find contours in the input image."""
        if MessageKeys.PAYLOAD not in msg:
            self.send(msg)
            return
        
        # Decode image from any supported format
        img, format_type = self.decode_image(msg[MessageKeys.PAYLOAD])
        if img is None:
            self.send(msg)
            return
        
        # Get parameters
        mode_str = self.config.get('mode', 'external')
        approx_str = self.config.get('approximation', 'simple')
        
        h, w = img.shape[:2]
        total_area = h * w
        
        # Convert normalized area to pixels
        min_area = self.get_config_float('min_area', 0.001) * total_area
        max_area_norm = self.get_config_float('max_area', 0.0)
        max_area = max_area_norm * total_area if max_area_norm > 0 else 0
        
        # Map mode string to OpenCV constant
        mode_map = {
            'external': cv2.RETR_EXTERNAL,
            'list': cv2.RETR_LIST,
            'tree': cv2.RETR_TREE,
            'ccomp': cv2.RETR_CCOMP
        }
        mode = mode_map.get(mode_str, cv2.RETR_EXTERNAL)
        
        # Map approximation string to OpenCV constant
        approx_map = {
            'none': cv2.CHAIN_APPROX_NONE,
            'simple': cv2.CHAIN_APPROX_SIMPLE,
            'tc89_l1': cv2.CHAIN_APPROX_TC89_L1,
            'tc89_kcos': cv2.CHAIN_APPROX_TC89_KCOS
        }
        approx = approx_map.get(approx_str, cv2.CHAIN_APPROX_SIMPLE)
        
        # Convert to grayscale if needed for contour finding
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()
        
        # Find contours
        contours, hierarchy = cv2.findContours(gray, mode, approx)
        
        # Filter and analyze contours
        contour_data = []
        filtered_contours = []
        
        for i, cnt in enumerate(contours):
            area = cv2.contourArea(cnt)
            
            # Filter by area
            if area < min_area:
                continue
            if max_area > 0 and area > max_area:
                continue
            
            filtered_contours.append(cnt)
            
            # Calculate properties
            perimeter = cv2.arcLength(cnt, True)
            x, y, bw, bh = cv2.boundingRect(cnt)
            
            # Centroid
            M = cv2.moments(cnt)
            if M['m00'] != 0:
                cx = int(M['m10'] / M['m00'])
                cy = int(M['m01'] / M['m00'])
            else:
                cx, cy = x + bw // 2, y + bh // 2
            
            # Circularity
            circularity = 0
            if perimeter > 0:
                circularity = 4 * np.pi * area / (perimeter * perimeter)
            
            contour_data.append({
                'index': len(contour_data),
                'area': float(area) / total_area,
                'area_px': float(area),
                'perimeter': float(perimeter) / (w + h),
                'perimeter_px': float(perimeter),
                'bbox': {
                    'x': float(x) / w, 'y': float(y) / h,
                    'width': float(bw) / w, 'height': float(bh) / h,
                    'x_px': int(x), 'y_px': int(y),
                    'width_px': int(bw), 'height_px': int(bh)
                },
                'centroid': {
                    'x': float(cx) / w, 'y': float(cy) / h,
                    'x_px': cx, 'y_px': cy
                },
                'circularity': float(circularity),
                'aspect_ratio': float(bw) / float(bh) if bh > 0 else 0
            })
        
        # Draw contours if requested
        draw_contours = self.get_config_bool('draw_contours', True)
        draw_bboxes = self.get_config_bool('draw_bboxes', False)
        
        # Ensure we have a color image to draw on
        if len(img.shape) == 2:
            output = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        else:
            output = img.copy()
        
        if draw_contours:
            cv2.drawContours(output, filtered_contours, -1, (0, 255, 0), 2)
        
        if draw_bboxes:
            for data in contour_data:
                bbox = data['bbox']
                cv2.rectangle(output, 
                              (bbox['x_px'], bbox['y_px']),
                              (bbox['x_px'] + bbox['width_px'], bbox['y_px'] + bbox['height_px']),
                              (255, 0, 0), 2)
        
        # Encode back to original format
        if MessageKeys.PAYLOAD not in msg or not isinstance(msg[MessageKeys.PAYLOAD], dict):
            msg[MessageKeys.PAYLOAD] = {}
        msg[MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH] = self.encode_image(output, format_type)
        msg['contours'] = contour_data
        msg['contour_count'] = len(contour_data)
        self.send(msg)
