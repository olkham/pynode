"""
Denormalize Coordinates Node - converts normalized coordinates (0.0-1.0) to pixels.
"""

from typing import Any, Dict, List
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Converts normalized coordinates (0.0-1.0) to pixel coordinates. Useful for applying normalized detections to images of different sizes.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with normalized coordinates to convert"),
    ("payload.image:", "Target image (used to get dimensions if not specified)")
)
_info.add_header("Supported Formats")
_info.add_bullets(
    ("Detections:", "msg.payload.detections[].bbox -> [x1, y1, x2, y2]"),
    ("YOLO format:", "msg.detections[].bbox or msg.predictions[].bbox"),
    ("Shapes:", "msg.shapes[].x1, y1, x2, y2, radius, etc."),
    ("Single bbox:", "msg.bbox or msg.payload.bbox"),
    ("Points:", "msg.points[] or msg.payload.points[]")
)
_info.add_header("Output")
_info.add_text("Same structure with coordinates converted to pixel values for the target image size.")


class DenormalizeCoordsNode(BaseNode):
    """
    Denormalize Coordinates node - converts normalized (0.0-1.0) to pixel coordinates.
    Handles detections, bboxes, shapes, points for various use cases.
    """
    info = str(_info)
    display_name = 'Denormalize Coords'
    icon = '📏'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'image_width': 0,
        'image_height': 0,
        'bbox_format': 'xyxy',
        'output_integers': True
    }
    
    properties = [
        {
            'name': 'image_width',
            'label': 'Image Width',
            'type': 'number',
            'default': DEFAULT_CONFIG['image_width'],
            'min': 0,
            'help': 'Target image width in pixels (0 = auto-detect from payload.image)'
        },
        {
            'name': 'image_height',
            'label': 'Image Height',
            'type': 'number',
            'default': DEFAULT_CONFIG['image_height'],
            'min': 0,
            'help': 'Target image height in pixels (0 = auto-detect from payload.image)'
        },
        {
            'name': 'bbox_format',
            'label': 'Output BBox Format',
            'type': 'select',
            'options': [
                {'value': 'xyxy', 'label': 'xyxy (x1, y1, x2, y2)'},
                {'value': 'xywh', 'label': 'xywh (x, y, width, height)'},
                {'value': 'cxcywh', 'label': 'cxcywh (center_x, center_y, w, h)'}
            ],
            'default': DEFAULT_CONFIG['bbox_format'],
            'help': 'Output bounding box format'
        },
        {
            'name': 'output_integers',
            'label': 'Output Integers',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['output_integers'],
            'help': 'Round pixel values to integers'
        }
    ]
    
    def __init__(self, node_id=None, name="denormalize coords"):
        super().__init__(node_id, name)
    
    def _get_image_dimensions(self, msg: Dict[str, Any]) -> tuple:
        """Get image dimensions from config or message."""
        w = self.get_config_int('image_width', 0)
        h = self.get_config_int('image_height', 0)
        
        if w > 0 and h > 0:
            return w, h
        
        # Check if dimensions are stored in message
        if msg.get('image_width', 0) > 0 and msg.get('image_height', 0) > 0:
            return msg['image_width'], msg['image_height']
        
        # Try to get from payload.image
        payload = msg.get('payload', {})
        if isinstance(payload, dict):
            img_data = payload.get('image', payload)
            if isinstance(img_data, dict):
                w = img_data.get('width', 0)
                h = img_data.get('height', 0)
                if w > 0 and h > 0:
                    return w, h
            
            # Try decoding image to get dimensions
            img, _ = self.decode_image(payload)
            if img is not None:
                return img.shape[1], img.shape[0]
        
        return 0, 0
    
    def _is_normalized(self, value) -> bool:
        """Check if a value appears to be normalized (0.0-1.0)."""
        if isinstance(value, (int, float)):
            return 0.0 <= value <= 1.0
        return False
    
    def _to_pixel(self, value, dimension: int, as_int: bool) -> Any:
        """Convert a normalized value to pixels."""
        if value is None:
            return None
        result = float(value) * dimension
        return int(round(result)) if as_int else result
    
    def _denormalize_bbox(self, bbox, w: int, h: int, as_int: bool) -> Any:
        """Denormalize a bounding box."""
        output_format = self.config.get('bbox_format', 'xyxy')
        
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            # Assume normalized xyxy input
            x1 = self._to_pixel(bbox[0], w, as_int)
            y1 = self._to_pixel(bbox[1], h, as_int)
            x2 = self._to_pixel(bbox[2], w, as_int)
            y2 = self._to_pixel(bbox[3], h, as_int)
            
            if output_format == 'xywh':
                result = [x1, y1, x2 - x1, y2 - y1]
            elif output_format == 'cxcywh':
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                bw = x2 - x1
                bh = y2 - y1
                if as_int:
                    result = [int(round(cx)), int(round(cy)), int(round(bw)), int(round(bh))]
                else:
                    result = [cx, cy, bw, bh]
            else:  # xyxy
                result = [x1, y1, x2, y2]
            
            # Add extra elements if present (confidence, class_id, etc.)
            if len(bbox) > 4:
                result.extend(bbox[4:])
            
            return result
        
        elif isinstance(bbox, dict):
            result = {}
            
            # Handle xyxy format
            if 'x1' in bbox and self._is_normalized(bbox['x1']):
                x1 = self._to_pixel(bbox['x1'], w, as_int)
                y1 = self._to_pixel(bbox['y1'], h, as_int)
                x2 = self._to_pixel(bbox.get('x2', 0), w, as_int)
                y2 = self._to_pixel(bbox.get('y2', 0), h, as_int)
                
                if output_format == 'xywh':
                    result['x'] = x1
                    result['y'] = y1
                    result['width'] = x2 - x1 if as_int else x2 - x1
                    result['height'] = y2 - y1 if as_int else y2 - y1
                elif output_format == 'cxcywh':
                    result['cx'] = int(round((x1 + x2) / 2)) if as_int else (x1 + x2) / 2
                    result['cy'] = int(round((y1 + y2) / 2)) if as_int else (y1 + y2) / 2
                    result['width'] = x2 - x1
                    result['height'] = y2 - y1
                else:
                    result['x1'] = x1
                    result['y1'] = y1
                    result['x2'] = x2
                    result['y2'] = y2
            
            # Handle xywh format
            elif 'x' in bbox and 'width' in bbox and self._is_normalized(bbox['x']):
                x = self._to_pixel(bbox['x'], w, as_int)
                y = self._to_pixel(bbox['y'], h, as_int)
                bw = self._to_pixel(bbox['width'], w, as_int)
                bh = self._to_pixel(bbox['height'], h, as_int)
                
                if output_format == 'xyxy':
                    result['x1'] = x
                    result['y1'] = y
                    result['x2'] = x + bw
                    result['y2'] = y + bh
                elif output_format == 'cxcywh':
                    result['cx'] = int(round(x + bw / 2)) if as_int else x + bw / 2
                    result['cy'] = int(round(y + bh / 2)) if as_int else y + bh / 2
                    result['width'] = bw
                    result['height'] = bh
                else:
                    result['x'] = x
                    result['y'] = y
                    result['width'] = bw
                    result['height'] = bh
            else:
                # Not normalized, copy as-is
                result = bbox.copy()
            
            # Copy non-coordinate fields
            for key in bbox:
                if key not in result and not key.endswith('_px'):
                    result[key] = bbox[key]
            
            return result
        
        return bbox
    
    def _denormalize_point(self, point, w: int, h: int, as_int: bool) -> Any:
        """Denormalize a point."""
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            if self._is_normalized(point[0]) and self._is_normalized(point[1]):
                return [self._to_pixel(point[0], w, as_int),
                        self._to_pixel(point[1], h, as_int)]
            return list(point)
        elif isinstance(point, dict):
            result = point.copy()
            if 'x' in point and self._is_normalized(point['x']):
                result['x'] = self._to_pixel(point['x'], w, as_int)
            if 'y' in point and self._is_normalized(point['y']):
                result['y'] = self._to_pixel(point['y'], h, as_int)
            return result
        return point
    
    def _denormalize_detection(self, det: Dict, w: int, h: int, as_int: bool) -> Dict:
        """Denormalize a detection dict."""
        result = det.copy()
        
        if 'bbox' in det:
            result['bbox'] = self._denormalize_bbox(det['bbox'], w, h, as_int)
        
        # Handle various coordinate fields
        for key in ['x', 'cx', 'center_x', 'x1', 'x2']:
            if key in det and self._is_normalized(det[key]):
                result[key] = self._to_pixel(det[key], w, as_int)
        
        for key in ['y', 'cy', 'center_y', 'y1', 'y2']:
            if key in det and self._is_normalized(det[key]):
                result[key] = self._to_pixel(det[key], h, as_int)
        
        for key in ['width', 'w', 'radius', 'size']:
            if key in det and self._is_normalized(det[key]):
                result[key] = self._to_pixel(det[key], w, as_int)
        
        for key in ['height', 'h']:
            if key in det and self._is_normalized(det[key]):
                result[key] = self._to_pixel(det[key], h, as_int)
        
        # Remove _px fields since we're outputting pixels
        for key in list(result.keys()):
            if key.endswith('_px'):
                del result[key]
        
        return result
    
    def _denormalize_shape(self, shape: Dict, w: int, h: int, as_int: bool) -> Dict:
        """Denormalize a shape dict (for draw node compatibility)."""
        return self._denormalize_detection(shape, w, h, as_int)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Denormalize coordinates in the message."""
        w, h = self._get_image_dimensions(msg)
        
        if w <= 0 or h <= 0:
            self.report_error("Could not determine image dimensions. Set width/height in config or provide image in payload.")
            self.send(msg)
            return
        
        as_int = self.get_config_bool('output_integers', True)
        
        # Store dimensions in message
        msg['image_width'] = w
        msg['image_height'] = h
        
        # Handle payload.detections
        payload = msg.get('payload', {})
        if isinstance(payload, dict) and 'detections' in payload:
            payload['detections'] = [
                self._denormalize_detection(d, w, h, as_int)
                for d in payload['detections']
            ]
        
        # Handle msg.detections (YOLO style)
        if 'detections' in msg and isinstance(msg['detections'], list):
            msg['detections'] = [
                self._denormalize_detection(d, w, h, as_int)
                for d in msg['detections']
            ]
        
        # Handle msg.predictions
        if 'predictions' in msg and isinstance(msg['predictions'], list):
            msg['predictions'] = [
                self._denormalize_detection(d, w, h, as_int)
                for d in msg['predictions']
            ]
        
        # Handle msg.shapes (draw node)
        if 'shapes' in msg and isinstance(msg['shapes'], list):
            msg['shapes'] = [
                self._denormalize_shape(s, w, h, as_int)
                for s in msg['shapes']
            ]
        
        # Handle single bbox
        if 'bbox' in msg:
            msg['bbox'] = self._denormalize_bbox(msg['bbox'], w, h, as_int)
        if isinstance(payload, dict) and 'bbox' in payload:
            payload['bbox'] = self._denormalize_bbox(payload['bbox'], w, h, as_int)
        
        # Handle points
        if 'points' in msg and isinstance(msg['points'], list):
            msg['points'] = [
                self._denormalize_point(p, w, h, as_int)
                for p in msg['points']
            ]
        if isinstance(payload, dict) and 'points' in payload:
            payload['points'] = [
                self._denormalize_point(p, w, h, as_int)
                for p in payload['points']
            ]
        
        # Handle circles
        if 'circles' in msg and isinstance(msg['circles'], list):
            msg['circles'] = [
                self._denormalize_detection(c, w, h, as_int)
                for c in msg['circles']
            ]
        
        # Handle lines
        if 'lines' in msg and isinstance(msg['lines'], list):
            msg['lines'] = [
                self._denormalize_detection(l, w, h, as_int)
                for l in msg['lines']
            ]
        
        # Handle contours
        if 'contours' in msg and isinstance(msg['contours'], list):
            msg['contours'] = [
                self._denormalize_detection(c, w, h, as_int)
                for c in msg['contours']
            ]
        
        # Handle blobs
        if 'blobs' in msg and isinstance(msg['blobs'], list):
            msg['blobs'] = [
                self._denormalize_detection(b, w, h, as_int)
                for b in msg['blobs']
            ]
        
        self.send(msg)
