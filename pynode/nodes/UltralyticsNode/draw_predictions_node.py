"""
Draw Predictions Node - draws YOLO predictions (bounding boxes, labels) on images.
Takes predictions from UltralyticsNode and original image, outputs annotated image.
"""

import base64
import cv2
import logging
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text("Draws YOLO detection results (bounding boxes and labels) on images.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with payload.predictions (from YOLO) and payload.image (base64)"),
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Annotated image with bounding boxes and labels drawn"),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Line Width:", "Thickness of bounding box lines"),
    ("Font Scale:", "Size of label text"),
    ("Text Color:", "Color of label text"),
    ("Show Confidence:", "Display confidence scores on labels"),
    ("Show Class:", "Display class names on labels"),
)


class DrawPredictionsNode(BaseNode):
    """
    Draw Predictions Node - visualizes YOLO detection results on images.
    Expects msg.payload.predictions (from YOLO) and msg.payload.image (base64).
    """
    display_name = 'Draw Predictions'
    info = str(_info)
    icon = '🎨'
    category = 'vision'
    color = '#FF6B9D'
    border_color = '#CC5680'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    ui_component = 'toggle'
    ui_component_config = {
        'action': 'toggle_drawing',
        'label': 'Draw'
    }
    
    DEFAULT_CONFIG = {
        'detections_path': 'payload.detections',
        'line_width': '2',
        'font_scale': '1',
        'text_thickness': '2',
        'text_color': 'white',
        'show_confidence': 'true',
        'show_class': 'true'
    }

    properties = [
        {
            'name': 'detections_path',
            'label': 'Detections/Tracks Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['detections_path'],
            'description': 'Dot-separated path to detections/tracks list (e.g. payload.detections or payload.tracks)'
        },
        {
            'name': 'enabled',
            'label': 'Drawing Enabled',
            'type': 'toggle',
            'action': 'toggle_drawing',
            'stateField': 'drawingEnabled',
            'help': 'Toggle drawing on/off'
        },
        {
            'name': 'line_width',
            'label': 'Line Width',
            'type': 'text',
            'default': DEFAULT_CONFIG['line_width'],
            'help': 'Thickness of bounding box lines'
        },
        {
            'name': 'font_scale',
            'label': 'Font Scale',
            'type': 'text',
            'default': DEFAULT_CONFIG['font_scale'],
            'help': 'Size of label text'
        },
        {
            'name': 'text_thickness',
            'label': 'Text Thickness',
            'type': 'text',
            'default': DEFAULT_CONFIG['text_thickness'],
            'help': 'Thickness of label text'
        },
        {
            'name': 'text_color',
            'label': 'Text Color',
            'type': 'select',
            'options': [
                {'value': 'white', 'label': 'White'},
                {'value': 'black', 'label': 'Black'},
                {'value': 'red', 'label': 'Red'},
                {'value': 'green', 'label': 'Green'},
                {'value': 'blue', 'label': 'Blue'},
                {'value': 'yellow', 'label': 'Yellow'}
            ],
            'default': DEFAULT_CONFIG['text_color'],
            'help': 'Color of label text'
        },
        {
            'name': 'show_confidence',
            'label': 'Show Confidence',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes'},
                {'value': 'false', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['show_confidence'],
            'help': 'Display confidence scores on labels'
        },
        {
            'name': 'show_class',
            'label': 'Show Class Name',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes'},
                {'value': 'false', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['show_class'],
            'help': 'Display class names on labels'
        }
    ]
    
    def __init__(self, node_id=None, name="Draw Predictions"):
        super().__init__(node_id, name)
        self.drawing_enabled = True  # Drawing is enabled by default
        self.configure({
            'line_width': '2',
            'font_scale': '0.5',
            'text_thickness': '1',
            'text_color': 'white',
            'show_confidence': 'true',
            'show_class': 'true'
        })
        
        # Color palette for different classes
        self.colors = [
            (255, 0, 0),     # Red
            (0, 255, 0),     # Green
            (0, 0, 255),     # Blue
            (255, 255, 0),   # Yellow
            (255, 0, 255),   # Magenta
            (0, 255, 255),   # Cyan
            (255, 128, 0),   # Orange
            (128, 0, 255),   # Purple
            (0, 255, 128),   # Spring Green
            (255, 0, 128),   # Rose
        ]
        
        # Text color mapping
        self.text_colors = {
            'white': (255, 255, 255),
            'black': (0, 0, 0),
            'red': (0, 0, 255),      # BGR format
            'green': (0, 255, 0),
            'blue': (255, 0, 0),
            'yellow': (0, 255, 255)
        }
    
    def _decode_image(self, image_data: str) -> np.ndarray:
        """Decode base64 image to numpy array."""
        try:
            # Remove data URL prefix if present
            if ',' in image_data:
                image_data = image_data.split(',', 1)[1]
            
            # Decode base64
            img_bytes = base64.b64decode(image_data)
            nparr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            return img
        except Exception as e:
            self.report_error(f"Failed to decode image: {str(e)}")
            return None
    
    def _encode_image(self, img: np.ndarray) -> str:
        """Encode numpy array to base64 JPEG."""
        try:
            _, buffer = cv2.imencode('.jpg', img)
            img_base64 = base64.b64encode(buffer).decode('utf-8')
            return img_base64
        except Exception as e:
            self.report_error(f"Failed to encode image: {str(e)}")
            return None
    
    def _get_color(self, class_id: int) -> tuple:
        """Get color for a class ID."""
        return self.colors[class_id % len(self.colors)]
    
    def toggle_drawing(self):
        """Toggle drawing on/off."""
        self.drawing_enabled = not self.drawing_enabled
        status = "enabled" if self.drawing_enabled else "disabled"
        logger.info(f"Draw Predictions ({self.id}): Drawing {status}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize node to dictionary for API/storage, including drawing state."""
        data = super().to_dict()
        data['drawingEnabled'] = self.drawing_enabled
        return data
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Draw predictions/tracks on image, with configurable path and track_id support."""
        # If drawing is disabled, pass through the message unchanged
        if not self.drawing_enabled:
            self.send(msg)
            return

        # Get detections/tracks path from config
        detections_path = self.config.get('detections_path', self.DEFAULT_CONFIG['detections_path'])

        detections = self._get_nested_value(msg, detections_path)
        payload = msg.get('payload', {})
        image_data = payload.get('image')

        if image_data is None:
            self.report_error("No image data in message. Expected msg.payload.image")
            return

        # Decode image using base node helper and make a copy to avoid modifying upstream data
        img, input_format = self.decode_image({'image': image_data})
        if img is None or input_format is None:
            self.report_error("Failed to decode image from payload")
            return
        img = img.copy()

        # Check if there are any detections/tracks
        if isinstance(detections, np.ndarray):
            has_detections = len(detections) > 0
        else:
            has_detections = bool(detections)

        if not has_detections:
            self.send(msg)
            return

        # Get configuration
        line_width = self.get_config_int('line_width', 2)
        font_scale = self.get_config_float('font_scale', 0.5)
        text_thickness = self.get_config_int('text_thickness', 1)
        text_color_name = self.config.get('text_color', 'white')
        text_color = self.text_colors.get(text_color_name, (255, 255, 255))
        show_confidence = self.get_config_bool('show_confidence', True)
        show_class = self.get_config_bool('show_class', True)

        # Draw each detection/track
        for i, det in enumerate(detections):
            try:
                bbox = det.get('bbox', [0, 0, 0, 0])
                if isinstance(bbox, np.ndarray):
                    bbox = bbox.tolist()
                x1, y1, x2, y2 = bbox
                class_id = det.get('class_id', 0)
                class_name = det.get('class_name', 'unknown')
                confidence = det.get('confidence', 0.0)
                track_id = det.get('track_id', None)

                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                color = self._get_color(class_id)
                cv2.rectangle(img, (x1, y1), (x2, y2), color, line_width)

                # Build label text
                label_parts = []
                if track_id is not None:
                    label_parts.append(f"TrackID: {track_id}")
                if show_class:
                    label_parts.append(class_name)
                if show_confidence:
                    label_parts.append(f"({confidence:.2f})")


                if label_parts:
                    label = '  '.join(label_parts)
                    (text_width, text_height), baseline = cv2.getTextSize(
                        label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1
                    )
                    # Clamp label position to image bounds
                    img_h, img_w = img.shape[:2]
                    # Default: draw above the box
                    label_top = y1 - text_height - baseline - 8
                    label_bottom = y1
                    text_org_y = y1 - baseline - 2
                    # Gradually clamp label so it stays within image bounds
                    if label_top < 0:
                        shift = -label_top
                        label_top += shift
                        label_bottom += shift
                        text_org_y += shift
                    if label_bottom > img_h:
                        shift = label_bottom - img_h
                        label_top -= shift
                        label_bottom -= shift
                        text_org_y -= shift
                    # Clamp horizontally
                    label_left = max(x1, 0)
                    label_right = min(x1 + text_width, img_w)
                    # Draw label background
                    cv2.rectangle(
                        img,
                        (label_left, label_top),
                        (label_right, label_bottom),
                        color,
                        -1  # Filled
                    )
                    # Draw label text
                    cv2.putText(
                        img,
                        label,
                        (label_left, text_org_y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        font_scale,
                        text_color,
                        text_thickness,
                        cv2.LINE_AA
                    )
            except Exception as e:
                import traceback
                self.report_error(f"Failed to draw detection {i}: {str(e)}\n{traceback.format_exc()}")
                continue

        # Encode image back to same format as input using base node helper
        encoded_image = self.encode_image(img, input_format)
        if encoded_image is not None:
            if not isinstance(msg.get('payload'), dict):
                msg['payload'] = {}
            msg['payload']['image'] = encoded_image
        else:
            self.report_error("Failed to encode output image")
            return

        self.send(msg)
