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
        
        # Decode image
        image = self._decode_image(payload)
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
            encoded = self._encode_image(crop_data['image'])
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
    
    def _decode_image(self, payload: Dict[str, Any]) -> np.ndarray:
        """Decode image from payload."""
        try:
            image = payload.get('image', None)
            if image is not None:
                img_format = image.get('format', None)
                encoding = image.get('encoding')
                data = image.get('data')
            
            if img_format == 'jpeg' and encoding == 'base64':
                img_bytes = base64.b64decode(data)
                nparr = np.frombuffer(img_bytes, np.uint8)
                return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            elif img_format == 'bgr' and encoding == 'raw':
                return np.array(data, dtype=np.uint8)
            else:
                self.report_error(f"Unsupported format: {img_format}/{encoding}")
                return None
        except Exception as e:
            self.report_error(f"Error decoding image: {e}")
            return None
    
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
    
    def _encode_image(self, image: np.ndarray) -> Dict[str, Any]:
        """Encode image to JPEG base64."""
        try:
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
        except Exception as e:
            self.report_error(f"Error encoding image: {e}")
            return None
