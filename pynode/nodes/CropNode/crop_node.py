"""
Crop Node - crops bounding boxes from images.
"""

import base64
import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Extracts cropped regions from images based on bounding box coordinates from detections or manual input.")
_info.add_header("Input")
_info.add_bullets(
    ("payload.image:", "Source image to crop from."),
    ("payload.detections:", "List of detections with 'bbox' field (when using detection mode)."),
)
_info.add_header("Output")
_info.add_bullets(
    ("payload.image:", "Cropped image data."),
    ("payload.bbox:", "Bounding box coordinates used for the crop (pixels)."),
    ("payload.bbox_normalized:", "Bounding box in normalized coordinates (0.0-1.0)."),
    ("payload.detection:", "Original detection info (if from detections)."),
    ("parts:", "Sequence info when outputting separate messages."),
)
_info.add_header("Coordinate Handling")
_info.add_text("Automatically detects normalized (0.0-1.0) vs pixel coordinates:")
_info.add_bullets(
    ("Normalized:", "All bbox values are between 0.0 and 1.0"),
    ("Pixels:", "Any bbox value > 1.0 indicates pixel coordinates"),
)
_info.add_header("Manual Coordinates")
_info.add_text("When using manual mode, coordinates are normalized (0.0-1.0):")
_info.add_bullets(
    ("0.0:", "Left/Top edge"),
    ("0.5:", "Center"),
    ("1.0:", "Right/Bottom edge"),
)
_info.add_header("Properties")
_info.add_bullets(
    ("Bounding Box Source:", "Use detections from message or manual coordinates."),
    ("Manual Coordinates:", "Normalized X1, Y1, X2, Y2 values (0.0-1.0)."),
    ("Output Mode:", "Send all crops in one message or separate messages."),
)


class CropNode(BaseNode):
    """
    Crop Node - extracts bounding box regions from images.
    Receives image data and bbox coordinates, outputs cropped images.
    """
    info = str(_info)
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
        'x1': 0.0,
        'y1': 0.0,
        'x2': 0.5,
        'y2': 0.5,
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
            'default': DEFAULT_CONFIG['x1'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.01,
            'help': 'Normalized X coordinate (0.0-1.0)',
            'showIf': {'bbox_source': 'manual'}
        },
        {
            'name': 'y1',
            'label': 'Y1 (top)',
            'type': 'number',
            'default': DEFAULT_CONFIG['y1'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.01,
            'help': 'Normalized Y coordinate (0.0-1.0)',
            'showIf': {'bbox_source': 'manual'}
        },
        {
            'name': 'x2',
            'label': 'X2 (right)',
            'type': 'number',
            'default': DEFAULT_CONFIG['x2'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.01,
            'help': 'Normalized X coordinate (0.0-1.0)',
            'showIf': {'bbox_source': 'manual'}
        },
        {
            'name': 'y2',
            'label': 'Y2 (bottom)',
            'type': 'number',
            'default': DEFAULT_CONFIG['y2'],
            'min': 0.0,
            'max': 1.0,
            'step': 0.01,
            'help': 'Normalized Y coordinate (0.0-1.0)',
            'showIf': {'bbox_source': 'manual'}
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
    
    def _is_normalized_bbox(self, bbox) -> bool:
        """Check if bbox appears to be normalized (all values 0.0-1.0)."""
        if not bbox or len(bbox) < 4:
            return False
        # If all coordinate values are <= 1.0, assume normalized
        return all(0.0 <= float(v) <= 1.0 for v in bbox[:4])
    
    def _convert_bbox_to_pixels(self, bbox, img_w: int, img_h: int) -> tuple:
        """Convert bbox to pixel coordinates, handling both normalized and pixel inputs."""
        if not bbox or len(bbox) < 4:
            return 0, 0, 0, 0
        
        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        
        # Auto-detect normalized vs pixel coordinates
        if self._is_normalized_bbox(bbox):
            # Convert normalized to pixels
            x1 = int(x1 * img_w)
            y1 = int(y1 * img_h)
            x2 = int(x2 * img_w)
            y2 = int(y2 * img_h)
        else:
            # Already pixels, just convert to int
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        
        return x1, y1, x2, y2
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Process incoming image and crop based on bounding boxes."""
        payload = msg.get(MessageKeys.PAYLOAD)
        if not payload or not isinstance(payload, dict):
            self.report_error("No image payload found")
            return
        
        # Decode image and track input format
        image, input_format = self._decode_image(payload)
        if image is None:
            return
        
        bbox_source = self.config.get('bbox_source', 'detections')
        crops = []
        
        # Get image dimensions for coordinate conversion
        img_h, img_w = image.shape[:2]
        
        if bbox_source == 'detections':
            # Extract from msg.payload.detections
            detections = payload.get('detections', [])
            if not detections:
                self.report_error("No detections found in payload")
                return

            for i, detection in enumerate(detections):
                bbox = detection.get('bbox')
                if bbox and len(bbox) >= 4:
                    # Auto-convert normalized coords to pixels
                    x1, y1, x2, y2 = self._convert_bbox_to_pixels(bbox, img_w, img_h)
                    crop = self._crop_image(image, x1, y1, x2, y2)
                    if crop is not None:
                        # Store both pixel and normalized bbox
                        bbox_normalized = [x1 / img_w, y1 / img_h, x2 / img_w, y2 / img_h]
                        crops.append({
                            MessageKeys.IMAGE.PATH: crop,
                            'bbox': [x1, y1, x2, y2],
                            'bbox_normalized': bbox_normalized,
                            'detection': detection,
                            'index': i
                        })
        else:
            # Use manual coordinates (normalized 0.0-1.0)
            norm_x1 = self.get_config_float('x1', 0.0)
            norm_y1 = self.get_config_float('y1', 0.0)
            norm_x2 = self.get_config_float('x2', 0.5)
            norm_y2 = self.get_config_float('y2', 0.5)
            
            x1 = int(norm_x1 * img_w)
            y1 = int(norm_y1 * img_h)
            x2 = int(norm_x2 * img_w)
            y2 = int(norm_y2 * img_h)
            
            crop = self._crop_image(image, x1, y1, x2, y2)
            if crop is not None:
                crops.append({
                    MessageKeys.IMAGE.PATH: crop,
                    'bbox': [x1, y1, x2, y2],
                    'bbox_normalized': [norm_x1, norm_y1, norm_x2, norm_y2],
                    'index': 0
                })
        
        if not crops:
            self.report_error("No valid crops produced")
            return
        
        output_mode = self.config.get('output_mode', 'separate')
        
        # For manual mode with single crop, output as single object not array
        if bbox_source == 'manual' and len(crops) == 1:
            crop_data = crops[0]
            encoded = self._encode_image(crop_data[MessageKeys.IMAGE.PATH], input_format)
            if encoded:
                # Single crop output
                msg[MessageKeys.PAYLOAD] = {
                    MessageKeys.IMAGE.PATH: encoded,
                    'bbox': crop_data['bbox'],
                    'bbox_normalized': crop_data.get('bbox_normalized'),
                    'index': crop_data['index']
                }
                msg[MessageKeys.TOPIC] = msg.get(MessageKeys.TOPIC, 'crop')
                self.send(msg)
        elif output_mode == 'separate':
            # Send each crop as a separate message
            for crop_data in crops:
                encoded = self._encode_image(crop_data[MessageKeys.IMAGE.PATH], input_format)
                if encoded:
                    msg_copy = msg.copy()
                    crop_info = {
                        MessageKeys.IMAGE.PATH: encoded,
                        'bbox': crop_data['bbox'],
                        'bbox_normalized': crop_data.get('bbox_normalized'),
                        'index': crop_data['index']
                    }
                    if 'detection' in crop_data:
                        crop_info['detection'] = crop_data['detection']
                    
                    msg_copy[MessageKeys.PAYLOAD] = crop_info
                    msg_copy[MessageKeys.TOPIC] = msg.get(MessageKeys.TOPIC, 'crop')
                    msg_copy['crop_count'] = len(crops)
                    msg_copy['parts'] = {'index': crop_data['index'], 'count': len(crops), 'id': msg.get(MessageKeys.MSG_ID)}
                    self.send(msg_copy)
        else:
            # Output all crops in one message as array
            encoded_crops = []
            for crop_data in crops:
                encoded = self._encode_image(crop_data[MessageKeys.IMAGE.PATH], input_format)
                if encoded:
                    crop_info = {
                        MessageKeys.IMAGE.PATH: encoded,
                        'bbox': crop_data['bbox'],
                        'bbox_normalized': crop_data.get('bbox_normalized'),
                        'index': crop_data['index']
                    }
                    if 'detection' in crop_data:
                        crop_info['detection'] = crop_data['detection']
                    encoded_crops.append(crop_info)

            msg[MessageKeys.PAYLOAD] = encoded_crops
            msg[MessageKeys.TOPIC] = msg.get(MessageKeys.TOPIC, 'crops')
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
