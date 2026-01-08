"""
OpenCV Blob Detection Node - detects blobs in images.
Uses SimpleBlobDetector to find circular/blob-like features.
"""

import cv2
import numpy as np
from typing import Any, Dict, List
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Detects blob-like features in images using OpenCV's SimpleBlobDetector.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Image to detect blobs in")
)
_info.add_header("Normalized Output")
_info.add_text("Blob positions and sizes are normalized (0.0-1.0) for resolution independence.")
_info.add_header("Filter Parameters")
_info.add_bullets(
    ("Area:", "Min/max blob area (normalized 0.0-1.0, relative to image area)"),
    ("Circularity:", "How circular the blob must be (1 = perfect circle)"),
    ("Convexity:", "How convex the blob must be"),
    ("Inertia:", "Shape elongation (1 = circle, 0 = line)"),
    ("Color:", "Filter for dark or light blobs")
)
_info.add_header("Output")
_info.add_text("Outputs image with keypoints drawn (optional) and msg.blobs containing detected blob data (normalized x, y, size).")


class BlobDetectorNode(BaseNode):
    """
    Blob Detector node - detects blobs in images using SimpleBlobDetector.
    Outputs keypoints with position, size, and other blob properties.
    """
    info = str(_info)
    display_name = 'Blob Detector'
    icon = '⬤'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'min_area': 0.0001,
        'max_area': 0.1,
        'min_circularity': 0.1,
        'min_convexity': 0.5,
        'min_inertia': 0.1,
        'filter_by_color': 'dark',
        'draw_keypoints': 'yes'
    }
    
    properties = [
        {
            'name': 'min_area',
            'label': 'Min Area',
            'type': 'number',
            'default': DEFAULT_CONFIG['min_area'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.0001,
            'help': 'Minimum blob area (normalized 0.0-1.0, relative to image area)'
        },
        {
            'name': 'max_area',
            'label': 'Max Area',
            'type': 'number',
            'default': DEFAULT_CONFIG['max_area'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.001,
            'help': 'Maximum blob area (normalized 0.0-1.0, relative to image area)'
        },
        {
            'name': 'min_circularity',
            'label': 'Min Circularity',
            'type': 'number',
            'default': DEFAULT_CONFIG['min_circularity'],
            'min': 0,
            'max': 1,
            'step': 0.1,
            'help': 'Minimum circularity (0-1, 1 is perfect circle)'
        },
        {
            'name': 'min_convexity',
            'label': 'Min Convexity',
            'type': 'number',
            'default': DEFAULT_CONFIG['min_convexity'],
            'min': 0,
            'max': 1,
            'step': 0.1,
            'help': 'Minimum convexity (0-1)'
        },
        {
            'name': 'min_inertia',
            'label': 'Min Inertia Ratio',
            'type': 'number',
            'default': DEFAULT_CONFIG['min_inertia'],
            'min': 0,
            'max': 1,
            'step': 0.1,
            'help': 'Minimum inertia ratio (0-1, 1 is circle, 0 is line)'
        },
        {
            'name': 'filter_by_color',
            'label': 'Filter by Color',
            'type': 'select',
            'options': [
                {'value': 'no', 'label': 'No'},
                {'value': 'dark', 'label': 'Dark blobs'},
                {'value': 'light', 'label': 'Light blobs'}
            ],
            'default': DEFAULT_CONFIG['filter_by_color'],
            'help': 'Filter blobs by color (dark or light)'
        },
        {
            'name': 'draw_keypoints',
            'label': 'Draw Keypoints',
            'type': 'select',
            'options': [
                {'value': 'yes', 'label': 'Yes'},
                {'value': 'no', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['draw_keypoints'],
            'help': 'Draw detected keypoints on output image'
        }
    ]
    
    def __init__(self, node_id=None, name="blob detector"):
        super().__init__(node_id, name)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Detect blobs in the input image."""
        if MessageKeys.PAYLOAD not in msg:
            self.send(msg)
            return
        
        # Decode image from any supported format
        img, format_type = self.decode_image(msg[MessageKeys.PAYLOAD])
        if img is None:
            self.send(msg)
            return
        
        h, w = img.shape[:2]
        total_area = h * w
        
        # Setup SimpleBlobDetector parameters
        params = cv2.SimpleBlobDetector_Params()
        
        # Area filter - convert normalized to pixels
        params.filterByArea = True
        params.minArea = self.get_config_float('min_area', 0.0001) * total_area
        params.maxArea = self.get_config_float('max_area', 0.1) * total_area
        
        # Circularity filter
        min_circularity = self.get_config_float('min_circularity', 0.1)
        if min_circularity > 0:
            params.filterByCircularity = True
            params.minCircularity = min_circularity
            params.maxCircularity = 1.0
        else:
            params.filterByCircularity = False
        
        # Convexity filter
        min_convexity = self.get_config_float('min_convexity', 0.5)
        if min_convexity > 0:
            params.filterByConvexity = True
            params.minConvexity = min_convexity
            params.maxConvexity = 1.0
        else:
            params.filterByConvexity = False
        
        # Inertia filter
        min_inertia = self.get_config_float('min_inertia', 0.1)
        if min_inertia > 0:
            params.filterByInertia = True
            params.minInertiaRatio = min_inertia
            params.maxInertiaRatio = 1.0
        else:
            params.filterByInertia = False
        
        # Color filter
        filter_color = self.config.get('filter_by_color', 'dark')
        if filter_color == 'no':
            params.filterByColor = False
        else:
            params.filterByColor = True
            params.blobColor = 0 if filter_color == 'dark' else 255
        
        # Create detector
        detector = cv2.SimpleBlobDetector_create(params)
        
        # Convert to grayscale if needed
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        
        # Detect blobs
        keypoints = detector.detect(gray)
        
        # Build blob data with normalized coordinates
        blobs = []
        for kp in keypoints:
            blobs.append({
                'x': float(kp.pt[0]) / w,
                'y': float(kp.pt[1]) / h,
                'size': float(kp.size) / w,
                'x_px': float(kp.pt[0]),
                'y_px': float(kp.pt[1]),
                'size_px': float(kp.size),
                'angle': float(kp.angle),
                'response': float(kp.response)
            })
        
        # Draw keypoints if requested
        draw = self.get_config_bool('draw_keypoints', True)
        if draw:
            output = cv2.drawKeypoints(img, keypoints, np.array([]),
                                       (0, 0, 255),
                                       cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)
        else:
            output = img
        
        if MessageKeys.PAYLOAD not in msg or not isinstance(msg[MessageKeys.PAYLOAD], dict):
            msg[MessageKeys.PAYLOAD] = {}
        msg[MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH] = self.encode_image(output, format_type)
        msg['blobs'] = blobs
        msg['blob_count'] = len(blobs)
        self.send(msg)
