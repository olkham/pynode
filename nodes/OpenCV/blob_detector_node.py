"""
OpenCV Blob Detection Node - detects blobs in images.
Uses SimpleBlobDetector to find circular/blob-like features.
"""

import cv2
import numpy as np
from typing import Any, Dict, List
from nodes.base_node import BaseNode


class BlobDetectorNode(BaseNode):
    """
    Blob Detector node - detects blobs in images using SimpleBlobDetector.
    Outputs keypoints with position, size, and other blob properties.
    """
    display_name = 'Blob Detector'
    icon = '⬤'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'min_area',
            'label': 'Min Area',
            'type': 'number',
            'default': 100,
            'min': 1,
            'help': 'Minimum blob area in pixels'
        },
        {
            'name': 'max_area',
            'label': 'Max Area',
            'type': 'number',
            'default': 50000,
            'min': 1,
            'help': 'Maximum blob area in pixels'
        },
        {
            'name': 'min_circularity',
            'label': 'Min Circularity',
            'type': 'number',
            'default': 0.1,
            'min': 0,
            'max': 1,
            'step': 0.1,
            'help': 'Minimum circularity (0-1, 1 is perfect circle)'
        },
        {
            'name': 'min_convexity',
            'label': 'Min Convexity',
            'type': 'number',
            'default': 0.5,
            'min': 0,
            'max': 1,
            'step': 0.1,
            'help': 'Minimum convexity (0-1)'
        },
        {
            'name': 'min_inertia',
            'label': 'Min Inertia Ratio',
            'type': 'number',
            'default': 0.1,
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
            'default': 'dark',
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
            'default': 'yes',
            'help': 'Draw detected keypoints on output image'
        }
    ]
    
    def __init__(self, node_id=None, name="blob detector"):
        super().__init__(node_id, name)
        self.configure({
            'min_area': 100,
            'max_area': 50000,
            'min_circularity': 0.1,
            'min_convexity': 0.5,
            'min_inertia': 0.1,
            'filter_by_color': 'dark',
            'draw_keypoints': 'yes'
        })
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Detect blobs in the input image."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        # Decode image from any supported format
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        # Setup SimpleBlobDetector parameters
        params = cv2.SimpleBlobDetector_Params()
        
        # Area filter
        params.filterByArea = True
        params.minArea = float(self.config.get('min_area', 100))
        params.maxArea = float(self.config.get('max_area', 50000))
        
        # Circularity filter
        min_circularity = float(self.config.get('min_circularity', 0.1))
        if min_circularity > 0:
            params.filterByCircularity = True
            params.minCircularity = min_circularity
            params.maxCircularity = 1.0
        else:
            params.filterByCircularity = False
        
        # Convexity filter
        min_convexity = float(self.config.get('min_convexity', 0.5))
        if min_convexity > 0:
            params.filterByConvexity = True
            params.minConvexity = min_convexity
            params.maxConvexity = 1.0
        else:
            params.filterByConvexity = False
        
        # Inertia filter
        min_inertia = float(self.config.get('min_inertia', 0.1))
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
        
        # Build blob data
        blobs = []
        for kp in keypoints:
            blobs.append({
                'x': float(kp.pt[0]),
                'y': float(kp.pt[1]),
                'size': float(kp.size),
                'angle': float(kp.angle),
                'response': float(kp.response)
            })
        
        # Draw keypoints if requested
        draw = self.config.get('draw_keypoints', 'yes') == 'yes'
        if draw:
            output = cv2.drawKeypoints(img, keypoints, np.array([]),
                                       (0, 0, 255),
                                       cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)
        else:
            output = img
        
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(output, format_type)
        msg['blobs'] = blobs
        msg['blob_count'] = len(blobs)
        self.send(msg)
