"""
Crop Node - crops bounding boxes from images.
"""

import base64
import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Extracts cropped regions from images. The box can come from detections, a custom message path, or manual coordinates.")
_info.add_header("Input")
_info.add_bullets(
    ("payload.image:", "Source image to crop from."),
    ("payload.detections:", "List of detections with 'bbox' field (detection mode)."),
    ("custom path:", "Any path (e.g. payload.crop) holding a box, when using path mode."),
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
_info.add_header("Custom Path Mode")
_info.add_text("Point 'Bounding Box Path' at a list of 4 numbers (e.g. "
               "payload.crop) or a dict, then pick how to read them:")
_info.add_bullets(
    ("Format:", "x1y1x2y2 (corners), xywh (top-left+size), cxcywh "
                "(center+size), or x1x2y1y2."),
    ("Space:", "Normalized (0.0-1.0, scaled by the image) or Absolute (pixels)."),
)
_info.add_text("Four daisy-chained Slider nodes writing payload.crop[0..3] can "
               "drive the box live.")
_info.add_header("Properties")
_info.add_bullets(
    ("Bounding Box Source:", "Detections, a custom message path, or manual coordinates."),
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
        'bbox_path': 'payload.crop',
        'bbox_format': 'x1y1x2y2',
        'bbox_space': 'normalized',
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
                {'value': 'path', 'label': 'From a custom message path'},
                {'value': 'manual', 'label': 'Manual coordinates'}
            ],
            'default': DEFAULT_CONFIG['bbox_source']
        },
        {
            'name': 'bbox_path',
            'label': 'Bounding Box Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['bbox_path'],
            'help': "Message path to the box: a list of 4 numbers (e.g. "
                    "payload.crop) or a dict keyed by the format's field names.",
            'showIf': {'bbox_source': 'path'}
        },
        {
            'name': 'bbox_format',
            'label': 'Coordinate Format',
            'type': 'select',
            'options': [
                {'value': 'x1y1x2y2', 'label': 'Corners: x1, y1, x2, y2'},
                {'value': 'xywh', 'label': 'Top-left + size: x, y, w, h'},
                {'value': 'cxcywh', 'label': 'Center + size: cx, cy, w, h'},
                {'value': 'x1x2y1y2', 'label': 'x1, x2, y1, y2'}
            ],
            'default': DEFAULT_CONFIG['bbox_format'],
            'showIf': {'bbox_source': 'path'}
        },
        {
            'name': 'bbox_space',
            'label': 'Coordinate Space',
            'type': 'select',
            'options': [
                {'value': 'normalized', 'label': 'Normalized (0.0-1.0)'},
                {'value': 'absolute', 'label': 'Absolute (pixels)'}
            ],
            'default': DEFAULT_CONFIG['bbox_space'],
            'showIf': {'bbox_source': 'path'}
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

    # Field names for a box supplied as a dict, per coordinate format.
    _FORMAT_KEYS = {
        'x1y1x2y2': ('x1', 'y1', 'x2', 'y2'),
        'xywh': ('x', 'y', 'w', 'h'),
        'cxcywh': ('cx', 'cy', 'w', 'h'),
        'x1x2y1y2': ('x1', 'x2', 'y1', 'y2'),
    }

    def _extract_four(self, value, fmt) -> list:
        """Pull four numbers from a list/tuple/array (positional) or a dict
        (keyed by the format's field names). Raises ValueError on bad input."""
        if isinstance(value, dict):
            keys = self._FORMAT_KEYS.get(fmt, self._FORMAT_KEYS['x1y1x2y2'])
            try:
                return [float(value[k]) for k in keys]
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError(f"dict needs keys {keys} for format '{fmt}': {e}")
        try:
            seq = list(value)
        except TypeError:
            raise ValueError(f"expected a list or dict of coordinates, got {type(value).__name__}")
        if len(seq) < 4:
            raise ValueError(f"expected 4 numbers, got {len(seq)}")
        try:
            return [float(seq[i]) for i in range(4)]
        except (TypeError, ValueError) as e:
            raise ValueError(f"non-numeric coordinate: {e}")

    def _corners_from_format(self, a, b, c, d, fmt) -> tuple:
        """Map four numbers in ``fmt`` ordering to (x1, y1, x2, y2) in the
        same coordinate space they arrived in."""
        if fmt == 'xywh':
            return a, b, a + c, b + d
        if fmt == 'cxcywh':
            return a - c / 2.0, b - d / 2.0, a + c / 2.0, b + d / 2.0
        if fmt == 'x1x2y1y2':
            return a, c, b, d  # x1, x2, y1, y2 -> x1, y1, x2, y2
        return a, b, c, d      # x1y1x2y2

    def _path_bbox_to_pixels(self, value, fmt: str, space: str,
                             img_w: int, img_h: int) -> tuple:
        """Turn a box at a custom path into pixel (x1, y1, x2, y2).

        ``fmt`` selects the coordinate ordering; ``space`` is 'normalized'
        (0.0-1.0, scaled by the image size) or 'absolute' (already pixels).
        Corners are sorted so a reversed/negative box still crops.
        """
        a, b, c, d = self._extract_four(value, fmt)
        x1, y1, x2, y2 = self._corners_from_format(a, b, c, d, fmt)
        if space == 'normalized':
            x1, x2 = x1 * img_w, x2 * img_w
            y1, y2 = y1 * img_h, y2 * img_h
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        return int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))

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
        elif bbox_source == 'path':
            # Read a single box from a user-specified message path, interpreted
            # per the configured coordinate format and space.
            bbox_path = str(self.config.get('bbox_path', 'payload.crop')).strip()
            fmt = self.config.get('bbox_format', 'x1y1x2y2')
            space = self.config.get('bbox_space', 'normalized')

            raw = self._get_nested_value(msg, bbox_path) if bbox_path else None
            if raw is None:
                self.report_error(f"No bounding box found at '{bbox_path}'")
                return
            try:
                x1, y1, x2, y2 = self._path_bbox_to_pixels(raw, fmt, space, img_w, img_h)
            except ValueError as e:
                self.report_error(f"Invalid bounding box at '{bbox_path}': {e}")
                return

            crop = self._crop_image(image, x1, y1, x2, y2)
            if crop is not None:
                crops.append({
                    MessageKeys.IMAGE.PATH: crop,
                    'bbox': [x1, y1, x2, y2],
                    'bbox_normalized': [x1 / img_w, y1 / img_h, x2 / img_w, y2 / img_h],
                    'index': 0
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
        
        # Single-box modes (manual / custom path) output one object, not an array
        if bbox_source in ('manual', 'path') and len(crops) == 1:
            crop_data = crops[0]
            encoded = self._encode_image(crop_data[MessageKeys.IMAGE.PATH], input_format)
            if encoded is not None:
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
                if encoded is not None:
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
                if encoded is not None:
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
    
    def _crop_image(self, image: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> 'np.ndarray | None':
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
    
    def _encode_image(self, image: np.ndarray, format_type: 'str | None'):
        """Encode image using BaseNode helper matching input format."""
        return self.encode_image(image, format_type)
