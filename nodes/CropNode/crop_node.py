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
    
    properties = [
        {
            'name': 'bbox_source',
            'label': 'Bounding Box Source',
            'type': 'select',
            'options': [
                {'value': 'detections', 'label': 'From msg.payload.detections'},
                {'value': 'manual', 'label': 'Manual coordinates'}
            ]
        },
        {
            'name': 'x1',
            'label': 'X1 (left)',
            'type': 'number',
            'default': 0
        },
        {
            'name': 'y1',
            'label': 'Y1 (top)',
            'type': 'number',
            'default': 0
        },
        {
            'name': 'x2',
            'label': 'X2 (right)',
            'type': 'number',
            'default': 100
        },
        {
            'name': 'y2',
            'label': 'Y2 (bottom)',
            'type': 'number',
            'default': 100
        },
        {
            'name': 'output_mode',
            'label': 'Output Mode',
            'type': 'select',
            'options': [
                {'value': 'all', 'label': 'All crops in one message'},
                {'value': 'separate', 'label': 'Separate messages per crop'}
            ]
        }
    ]
    
    def __init__(self, node_id=None, name="crop"):
        super().__init__(node_id, name)
        self.configure({
            'bbox_source': 'detections',
            'x1': 0,
            'y1': 0,
            'x2': 100,
            'y2': 100,
            'output_mode': 'separate',
            'drop_messages': 'false'
        })
    
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
            x1 = int(self.config.get('x1', 0))
            y1 = int(self.config.get('y1', 0))
            x2 = int(self.config.get('x2', 100))
            y2 = int(self.config.get('y2', 100))
            
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

        out_msg = self.create_message(
            payload=encoded_crops,
            topic=msg.get('topic', 'crops'),
            crop_count=len(encoded_crops)
        )
        self.send(out_msg)
    
    def _decode_image(self, payload: Dict[str, Any]):
        """Decode image from payload. Returns (image, format_info) tuple."""
        try:
            image_data = payload.get('image', None)
            if image_data is None:
                self.report_error("No image in payload")
                return None, None
            
            # Handle direct numpy array
            if isinstance(image_data, np.ndarray):
                return image_data, {'type': 'numpy_direct'}
            
            # Handle dict format
            if isinstance(image_data, dict):
                img_format = image_data.get('format')
                encoding = image_data.get('encoding')
                data = image_data.get('data')
                
                if img_format == 'bgr' and encoding == 'numpy':
                    # NumPy array format
                    if isinstance(data, np.ndarray):
                        return data, {'type': 'dict', 'format': 'bgr', 'encoding': 'numpy'}
                    else:
                        self.report_error("Expected numpy array in data field")
                        return None, None
                elif img_format == 'jpeg' and encoding == 'base64':
                    # Base64 JPEG format
                    img_bytes = base64.b64decode(data)
                    nparr = np.frombuffer(img_bytes, np.uint8)
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    return img, {'type': 'dict', 'format': 'jpeg', 'encoding': 'base64'}
                elif img_format == 'bgr' and encoding == 'raw':
                    # Raw list format
                    img = np.array(data, dtype=np.uint8)
                    return img, {'type': 'dict', 'format': 'bgr', 'encoding': 'raw'}
                else:
                    self.report_error(f"Unsupported format: {img_format}/{encoding}")
                    return None, None
            
            # Handle direct base64 string
            if isinstance(image_data, str):
                img_bytes = base64.b64decode(image_data)
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                return img, {'type': 'base64_string'}
            
            self.report_error(f"Unsupported image_data type: {type(image_data)}")
            return None, None
        except Exception as e:
            self.report_error(f"Error decoding image: {e}")
            return None, None
    
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
    
    def _encode_image(self, image: np.ndarray, format_info: Dict[str, str]):
        """Encode image matching input format."""
        try:
            if format_info['type'] == 'numpy_direct':
                # Output as direct numpy array
                return image
            elif format_info['type'] == 'dict':
                if format_info['format'] == 'bgr' and format_info['encoding'] == 'numpy':
                    # Output as numpy dict format
                    return {
                        'format': 'bgr',
                        'encoding': 'numpy',
                        'data': image,
                        'width': image.shape[1],
                        'height': image.shape[0]
                    }
                elif format_info['format'] == 'bgr' and format_info['encoding'] == 'raw':
                    # Output as raw list format
                    return {
                        'format': 'bgr',
                        'encoding': 'raw',
                        'data': image.tolist(),
                        'width': image.shape[1],
                        'height': image.shape[0]
                    }
                else:
                    # Default to JPEG base64 for other dict formats
                    ret, buffer = cv2.imencode('.jpg', image)
                    if ret:
                        jpeg_bytes = buffer.tobytes()
                        jpeg_base64 = base64.b64encode(jpeg_bytes).decode('utf-8')
                        return {
                            'format': 'jpeg',
                            'encoding': 'base64',
                            'data': jpeg_base64,
                            'width': image.shape[1],
                            'height': image.shape[0]
                        }
                    else:
                        self.report_error("Failed to encode image")
                        return None
            elif format_info['type'] == 'base64_string':
                # Output as direct base64 string
                ret, buffer = cv2.imencode('.jpg', image)
                if ret:
                    jpeg_bytes = buffer.tobytes()
                    return base64.b64encode(jpeg_bytes).decode('utf-8')
                else:
                    self.report_error("Failed to encode image")
                    return None
            else:
                self.report_error(f"Unknown format type: {format_info['type']}")
                return None
        except Exception as e:
            self.report_error(f"Error encoding image: {e}")
            return None
