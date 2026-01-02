"""
Normalize Coordinates Node - converts pixel coordinates to normalized (0.0-1.0).
"""

from typing import Any, Dict, List
from pynode.nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Converts pixel coordinates to normalized coordinates (0.0-1.0). Useful for making detection outputs resolution-independent.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with coordinates to normalize"),
    ("payload.image:", "Source image (used to get dimensions if not specified)")
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
_info.add_text("Same structure with coordinates converted to normalized (0.0-1.0) values. Original pixel values preserved with '_px' suffix.")


class NormalizeCoordsNode(BaseNode):
    """
    Normalize Coordinates node - converts pixel coordinates to normalized (0.0-1.0).
    Handles detections, bboxes, shapes, points from various inference engines.
    """
    info = str(_info)
    display_name = 'Normalize Coords'
    icon = '📐'
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
        'preserve_pixels': True
    }
    
    properties = [
        {
            'name': 'image_width',
            'label': 'Image Width',
            'type': 'number',
            'default': DEFAULT_CONFIG['image_width'],
            'min': 0,
            'help': 'Image width in pixels (0 = auto-detect from payload.image)'
        },
        {
            'name': 'image_height',
            'label': 'Image Height',
            'type': 'number',
            'default': DEFAULT_CONFIG['image_height'],
            'min': 0,
            'help': 'Image height in pixels (0 = auto-detect from payload.image)'
        },
        {
            'name': 'bbox_format',
            'label': 'BBox Format',
            'type': 'select',
            'options': [
                {'value': 'xyxy', 'label': 'xyxy (x1, y1, x2, y2)'},
                {'value': 'xywh', 'label': 'xywh (x, y, width, height)'},
                {'value': 'cxcywh', 'label': 'cxcywh (center_x, center_y, w, h)'}
            ],
            'default': DEFAULT_CONFIG['bbox_format'],
            'help': 'Input bounding box format'
        },
        {
            'name': 'preserve_pixels',
            'label': 'Preserve Pixel Values',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['preserve_pixels'],
            'help': 'Keep original pixel values with _px suffix'
        }
    ]
    
    def __init__(self, node_id=None, name="normalize coords"):
        super().__init__(node_id, name)
    
    def _get_image_dimensions(self, msg: Dict[str, Any]) -> tuple:
        """Get image dimensions from config or message."""
        w = self.get_config_int('image_width', 0)
        h = self.get_config_int('image_height', 0)
        
        if w > 0 and h > 0:
            return w, h
        
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
    
    def _normalize_bbox(self, bbox, w: int, h: int, preserve: bool) -> Any:
        """Normalize a bounding box."""
        bbox_format = self.config.get('bbox_format', 'xyxy')
        
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            x1, y1, x2, y2 = bbox[:4]
            
            if bbox_format == 'xywh':
                # Convert xywh to xyxy first
                x2 = x1 + x2
                y2 = y1 + y2
            elif bbox_format == 'cxcywh':
                # Convert center format to xyxy
                cx, cy, bw, bh = bbox[:4]
                x1 = cx - bw / 2
                y1 = cy - bh / 2
                x2 = cx + bw / 2
                y2 = cy + bh / 2
            
            result = [
                float(x1) / w if w > 0 else 0,
                float(y1) / h if h > 0 else 0,
                float(x2) / w if w > 0 else 0,
                float(y2) / h if h > 0 else 0
            ]
            
            # Add extra elements if present (confidence, class_id, etc.)
            if len(bbox) > 4:
                result.extend(bbox[4:])
            
            return result
        
        elif isinstance(bbox, dict):
            result = {}
            
            # Handle various bbox dict formats
            if 'x1' in bbox:
                result['x1'] = float(bbox['x1']) / w if w > 0 else 0
                result['y1'] = float(bbox['y1']) / h if h > 0 else 0
                result['x2'] = float(bbox.get('x2', 0)) / w if w > 0 else 0
                result['y2'] = float(bbox.get('y2', 0)) / h if h > 0 else 0
                if preserve:
                    result['x1_px'] = bbox['x1']
                    result['y1_px'] = bbox['y1']
                    result['x2_px'] = bbox.get('x2', 0)
                    result['y2_px'] = bbox.get('y2', 0)
            
            if 'x' in bbox and 'width' in bbox:
                result['x'] = float(bbox['x']) / w if w > 0 else 0
                result['y'] = float(bbox['y']) / h if h > 0 else 0
                result['width'] = float(bbox['width']) / w if w > 0 else 0
                result['height'] = float(bbox['height']) / h if h > 0 else 0
                if preserve:
                    result['x_px'] = bbox['x']
                    result['y_px'] = bbox['y']
                    result['width_px'] = bbox['width']
                    result['height_px'] = bbox['height']
            
            # Copy non-coordinate fields
            for key in bbox:
                if key not in result and not key.endswith('_px'):
                    result[key] = bbox[key]
            
            return result
        
        return bbox
    
    def _normalize_point(self, point, w: int, h: int, preserve: bool) -> Any:
        """Normalize a point."""
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            return [float(point[0]) / w if w > 0 else 0,
                    float(point[1]) / h if h > 0 else 0]
        elif isinstance(point, dict):
            result = {
                'x': float(point.get('x', 0)) / w if w > 0 else 0,
                'y': float(point.get('y', 0)) / h if h > 0 else 0
            }
            if preserve:
                result['x_px'] = point.get('x', 0)
                result['y_px'] = point.get('y', 0)
            # Copy other fields
            for key in point:
                if key not in ['x', 'y'] and not key.endswith('_px'):
                    result[key] = point[key]
            return result
        return point
    
    def _normalize_detection(self, det: Dict, w: int, h: int, preserve: bool) -> Dict:
        """Normalize a detection dict."""
        result = det.copy()
        
        if 'bbox' in det:
            result['bbox'] = self._normalize_bbox(det['bbox'], w, h, preserve)
        
        # Handle various coordinate fields
        for key in ['x', 'cx', 'center_x']:
            if key in det and not isinstance(det[key], dict):
                result[key] = float(det[key]) / w if w > 0 else 0
                if preserve:
                    result[f'{key}_px'] = det[key]
        
        for key in ['y', 'cy', 'center_y']:
            if key in det and not isinstance(det[key], dict):
                result[key] = float(det[key]) / h if h > 0 else 0
                if preserve:
                    result[f'{key}_px'] = det[key]
        
        for key in ['width', 'w', 'radius']:
            if key in det:
                result[key] = float(det[key]) / w if w > 0 else 0
                if preserve:
                    result[f'{key}_px'] = det[key]
        
        for key in ['height', 'h']:
            if key in det:
                result[key] = float(det[key]) / h if h > 0 else 0
                if preserve:
                    result[f'{key}_px'] = det[key]
        
        # Handle x1, y1, x2, y2 directly on detection
        if 'x1' in det:
            result['x1'] = float(det['x1']) / w if w > 0 else 0
            result['y1'] = float(det['y1']) / h if h > 0 else 0
            if preserve:
                result['x1_px'] = det['x1']
                result['y1_px'] = det['y1']
        if 'x2' in det:
            result['x2'] = float(det['x2']) / w if w > 0 else 0
            result['y2'] = float(det['y2']) / h if h > 0 else 0
            if preserve:
                result['x2_px'] = det['x2']
                result['y2_px'] = det['y2']
        
        return result
    
    def _normalize_shape(self, shape: Dict, w: int, h: int, preserve: bool) -> Dict:
        """Normalize a shape dict (for draw node compatibility)."""
        return self._normalize_detection(shape, w, h, preserve)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Normalize coordinates in the message."""
        w, h = self._get_image_dimensions(msg)
        
        if w <= 0 or h <= 0:
            self.report_error("Could not determine image dimensions. Set width/height in config or provide image in payload.")
            self.send(msg)
            return
        
        preserve = self.get_config_bool('preserve_pixels', True)
        
        # Store dimensions in message
        msg['image_width'] = w
        msg['image_height'] = h
        
        # Handle payload.detections
        payload = msg.get('payload', {})
        if isinstance(payload, dict) and 'detections' in payload:
            payload['detections'] = [
                self._normalize_detection(d, w, h, preserve)
                for d in payload['detections']
            ]
        
        # Handle msg.detections (YOLO style)
        if 'detections' in msg and isinstance(msg['detections'], list):
            msg['detections'] = [
                self._normalize_detection(d, w, h, preserve)
                for d in msg['detections']
            ]
        
        # Handle msg.predictions
        if 'predictions' in msg and isinstance(msg['predictions'], list):
            msg['predictions'] = [
                self._normalize_detection(d, w, h, preserve)
                for d in msg['predictions']
            ]
        
        # Handle msg.shapes (draw node)
        if 'shapes' in msg and isinstance(msg['shapes'], list):
            msg['shapes'] = [
                self._normalize_shape(s, w, h, preserve)
                for s in msg['shapes']
            ]
        
        # Handle single bbox
        if 'bbox' in msg:
            msg['bbox'] = self._normalize_bbox(msg['bbox'], w, h, preserve)
        if isinstance(payload, dict) and 'bbox' in payload:
            payload['bbox'] = self._normalize_bbox(payload['bbox'], w, h, preserve)
        
        # Handle points
        if 'points' in msg and isinstance(msg['points'], list):
            msg['points'] = [
                self._normalize_point(p, w, h, preserve)
                for p in msg['points']
            ]
        if isinstance(payload, dict) and 'points' in payload:
            payload['points'] = [
                self._normalize_point(p, w, h, preserve)
                for p in payload['points']
            ]
        
        # Handle circles
        if 'circles' in msg and isinstance(msg['circles'], list):
            msg['circles'] = [
                self._normalize_detection(c, w, h, preserve)
                for c in msg['circles']
            ]
        
        # Handle lines
        if 'lines' in msg and isinstance(msg['lines'], list):
            msg['lines'] = [
                self._normalize_detection(l, w, h, preserve)
                for l in msg['lines']
            ]
        
        # Handle contours
        if 'contours' in msg and isinstance(msg['contours'], list):
            msg['contours'] = [
                self._normalize_detection(c, w, h, preserve)
                for c in msg['contours']
            ]
        
        # Handle blobs
        if 'blobs' in msg and isinstance(msg['blobs'], list):
            msg['blobs'] = [
                self._normalize_detection(b, w, h, preserve)
                for b in msg['blobs']
            ]
        
        self.send(msg)
