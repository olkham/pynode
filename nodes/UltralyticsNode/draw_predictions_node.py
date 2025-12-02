"""
Draw Predictions Node - draws YOLO predictions (bounding boxes, labels) on images.
Takes predictions from UltralyticsNode and original image, outputs annotated image.
"""

import base64
import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class DrawPredictionsNode(BaseNode):
    """
    Draw Predictions Node - visualizes YOLO detection results on images.
    Expects msg.payload.predictions (from YOLO) and msg.payload.image (base64).
    """
    display_name = 'Draw Predictions'
    icon = '🎨'
    category = 'vision'
    color = '#FF6B9D'
    border_color = '#CC5680'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    properties = [
        {
            'name': 'enabled',
            'label': 'Draw Enabled',
            'type': 'button',
            'action': 'toggle_drawing',
            'help': 'Toggle drawing on/off'
        },
        {
            'name': 'line_width',
            'label': 'Line Width',
            'type': 'text',
            'default': '2',
            'help': 'Thickness of bounding box lines'
        },
        {
            'name': 'font_scale',
            'label': 'Font Scale',
            'type': 'text',
            'default': '1',
            'help': 'Size of label text'
        },
        {
            'name': 'text_thickness',
            'label': 'Text Thickness',
            'type': 'text',
            'default': '2',
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
            'default': 'white',
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
            'default': 'true',
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
            'default': 'true',
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
        print(f"Draw Predictions ({self.id}): Drawing {status}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize node to dictionary for API/storage, including drawing state."""
        data = super().to_dict()
        data['drawingEnabled'] = self.drawing_enabled
        return data
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Draw predictions on image."""
        payload = msg.get('payload', {})
        
        # If drawing is disabled, pass through the message unchanged
        if not self.drawing_enabled:
            self.send(msg)
            return
        
        # Get detections and image from message
        detections = payload.get('detections', [])
        image_data = payload.get('image')
        
        if image_data is None:
            self.report_error("No image data in message. Expected msg.payload.image")
            return
        
        # Handle image data format (can be object with 'data' field, direct base64 string, or numpy array)
        if isinstance(image_data, np.ndarray):
            # Direct numpy array - make a copy to avoid modifying upstream data
            img = image_data.copy()
        elif isinstance(image_data, dict):
            data_field = image_data.get('data')
            # Check if data is a numpy array
            if isinstance(data_field, np.ndarray):
                # Make a copy to avoid modifying upstream data
                img = data_field.copy()
            elif data_field:
                # It's a base64 string
                img = self._decode_image(data_field)
                if img is None:
                    return
            else:
                self.report_error("Image data is empty")
                return
        else:
            # Direct base64 string
            if not image_data:
                self.report_error("Image data is empty")
                return
            # Decode image
            img = self._decode_image(image_data)
            if img is None:
                return
        
        # Check if there are any detections (handle both list and numpy array)
        if isinstance(detections, np.ndarray):
            has_detections = len(detections) > 0
        else:
            has_detections = bool(detections)
        
        if not has_detections:
            # No detections, just pass through the original message
            self.send(msg)
            return
        
        # Get configuration
        line_width = int(self.config.get('line_width', '2'))
        font_scale = float(self.config.get('font_scale', '0.5'))
        text_thickness = int(self.config.get('text_thickness', '1'))
        text_color_name = self.config.get('text_color', 'white')
        text_color = self.text_colors.get(text_color_name, (255, 255, 255))
        show_confidence = self.config.get('show_confidence', 'true') == 'true'
        show_class = self.config.get('show_class', 'true') == 'true'
        
        # Draw each detection
        for i, det in enumerate(detections):
            try:
                # Get detection data (YOLO node uses 'bbox' not 'box')
                bbox = det.get('bbox', [0, 0, 0, 0])
                
                # Convert bbox to list if it's a numpy array
                if isinstance(bbox, np.ndarray):
                    bbox = bbox.tolist()
                
                x1, y1, x2, y2 = bbox
                class_id = det.get('class_id', 0)
                class_name = det.get('class_name', 'unknown')
                confidence = det.get('confidence', 0.0)
                
                # Convert coordinates to integers
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                
                # Get color for this class
                color = self._get_color(class_id)
                
                # Draw bounding box
                cv2.rectangle(img, (x1, y1), (x2, y2), color, line_width)
                
                # Build label text
                label_parts = []
                if show_class:
                    label_parts.append(class_name)
                if show_confidence:
                    label_parts.append(f"{confidence:.2f}")
                
                if label_parts:
                    label = ' '.join(label_parts)
                    
                    # Calculate label size
                    (text_width, text_height), baseline = cv2.getTextSize(
                        label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1
                    )
                    
                    # Draw label background
                    cv2.rectangle(
                        img,
                        (x1, y1 - text_height - baseline - 4),
                        (x1 + text_width, y1),
                        color,
                        -1  # Filled
                    )
                    
                    # Draw label text
                    cv2.putText(
                        img,
                        label,
                        (x1, y1 - baseline - 2),
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
        
        # Update message with annotated image (keep same format as input)
        output_msg = msg.copy()
        
        if isinstance(image_data, np.ndarray):
            # Direct numpy array - output as numpy array
            output_msg['payload']['image'] = img
        elif isinstance(image_data, dict):
            # Check if input was numpy format
            input_format = image_data.get('format')
            input_encoding = image_data.get('encoding')
            
            if input_format == 'bgr' and input_encoding == 'numpy':
                # Keep as numpy format
                output_msg['payload']['image'] = {
                    'format': 'bgr',
                    'encoding': 'numpy',
                    'data': img,
                    'width': img.shape[1],
                    'height': img.shape[0]
                }
            else:
                # Encode to base64 for other formats
                annotated_image = self._encode_image(img)
                if annotated_image is None:
                    return
                # Update the data field in the image object
                output_msg['payload']['image'] = {
                    'format': 'jpeg',
                    'encoding': 'base64',
                    'data': annotated_image,
                    'width': img.shape[1],
                    'height': img.shape[0]
                }
        else:
            # Direct base64 string
            annotated_image = self._encode_image(img)
            if annotated_image is None:
                return
            output_msg['payload']['image'] = annotated_image
        
        self.send(output_msg)
