"""
Crop Node - crops bounding boxes from images.
"""

import base64
import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class CropNode(BaseNode):
    """
    Crop Node - extracts bounding box regions from images.
    Receives image data and bbox coordinates, outputs cropped images.
    """
    display_name = 'Crop'
    icon = '✂️'
    category = 'vision'
    color = '#98D8C8'
    border_color = '#6DB6A3'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'bbox_source': 'detections',
        'x1': 0,
        'y1': 0,
        'x2': 100,
        'y2': 100,
        'output_mode': 'separate',
        'drop_messages': False
    }
    
    properties = [
        {
            'name': 'bbox_source',
            'label': 'Bounding Box Source',
            'type': 'select',
            'options': [
                {'value': 'detections', 'label': 'From msg.payload.detections'},
                {'value': 'manual', 'label': 'Manual coordinates'}
            ],
            'default': DEFAULT_CONFIG['bbox_source']
        },
        {
            'name': 'x1',
            'label': 'X1 (left)',
            'type': 'number',
            'default': DEFAULT_CONFIG['x1']
        },
        {
            'name': 'y1',
            'label': 'Y1 (top)',
            'type': 'number',
            'default': DEFAULT_CONFIG['y1']
        },
        {
            'name': 'x2',
            'label': 'X2 (right)',
            'type': 'number',
            'default': DEFAULT_CONFIG['x2']
        },
        {
            'name': 'y2',
            'label': 'Y2 (bottom)',
            'type': 'number',
            'default': DEFAULT_CONFIG['y2']
        },
        {
            'name': 'output_mode',
            'label': 'Output Mode',
            'type': 'select',
            'options': [
                {'value': 'all', 'label': 'All crops in one message'},
                {'value': 'separate', 'label': 'Separate messages per crop'}
            ],
            'default': DEFAULT_CONFIG['output_mode']
        }
    ]
    
    def __init__(self, node_id=None, name="crop"):
        super().__init__(node_id, name)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Process incoming image and crop based on bounding boxes."""
        payload = msg.get('payload')
        if not payload or not isinstance(payload, dict):
            self.report_error("No image payload found")
            return
        
        # Decode image and track input format
        image, input_format = self._decode_image(payload)
        if image is None:
            return
        
        bbox_source = self.config.get('bbox_source', 'detections')
        crops = []
        
        if bbox_source == 'detections':
            # Extract from msg.payload.detections
            detections = payload.get('detections', [])
            if not detections:
                self.report_error("No detections found in payload")
                return

            for i, detection in enumerate(detections):
                bbox = detection.get('bbox')
                if bbox and len(bbox) >= 4:
                    x1, y1, x2, y2 = map(int, bbox[:4])
                    crop = self._crop_image(image, x1, y1, x2, y2)
                    if crop is not None:
                        crops.append({
                            'image': crop,
                            'bbox': [x1, y1, x2, y2],
                            'detection': detection,
                            'index': i
                        })
        else:
            # Use manual coordinates
            x1 = self.get_config_int('x1', 0)
            y1 = self.get_config_int('y1', 0)
            x2 = self.get_config_int('x2', 100)
            y2 = self.get_config_int('y2', 100)
            
            crop = self._crop_image(image, x1, y1, x2, y2)
            if crop is not None:
                crops.append({
                    'image': crop,
                    'bbox': [x1, y1, x2, y2],
                    'index': 0
                })
        
        if not crops:
            self.report_error("No valid crops produced")
            return
        
        # Always output a list of crops as the payload
        encoded_crops = []
        for crop_data in crops:
            encoded = self._encode_image(crop_data['image'], input_format)
            if encoded:
                crop_info = {
                    'image': encoded,
                    'bbox': crop_data['bbox'],
                    'index': crop_data['index']
                }
                if 'detection' in crop_data:
                    crop_info['detection'] = crop_data['detection']
                encoded_crops.append(crop_info)

        # Preserve original message properties (like frame_count) and update payload
        # Note: send() handles deep copying, so we modify msg directly
        msg['payload'] = encoded_crops
        msg['topic'] = msg.get('topic', 'crops')
        msg['crop_count'] = len(encoded_crops)
        self.send(msg)
    
    def _decode_image(self, payload: Dict[str, Any]):
        """Decode image from payload using BaseNode helper. Returns (image, format_type) tuple."""
        return self.decode_image(payload)
    
    def _crop_image(self, image: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
        """Crop image to bounding box."""
        try:
            h, w = image.shape[:2]
            # Clamp coordinates
            x1 = max(0, min(x1, w))
            y1 = max(0, min(y1, h))
            x2 = max(0, min(x2, w))
            y2 = max(0, min(y2, h))
            
            if x2 <= x1 or y2 <= y1:
                self.report_error(f"Invalid bbox: [{x1}, {y1}, {x2}, {y2}]")
                return None
            
            return image[y1:y2, x1:x2]
        except Exception as e:
            self.report_error(f"Error cropping image: {e}")
            return None
    
    def _encode_image(self, image: np.ndarray, format_type: str):
        """Encode image using BaseNode helper matching input format."""
        return self.encode_image(image, format_type)
