"""
Ultralytics YOLOv8 node - performs object detection on images.
Receives image data from camera nodes and outputs inference results.
"""

import base64
import cv2
import numpy as np
from typing import Any, Dict, List
from nodes.base_node import BaseNode
import torch


class UltralyticsNode(BaseNode):
    """
    Ultralytics YOLOv8 node - performs object detection inference.
    Receives images and outputs detection results with optional visualization.
    """
    # Visual properties
    display_name = 'YOLO'
    icon = '🎯'
    category = 'vision'
    color = '#00D9FF'
    border_color = '#00A8CC'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    @staticmethod
    def _get_device_options() -> List[Dict[str, str]]:
        """Get available CUDA devices for the dropdown."""
        devices = [{'value': 'cpu', 'label': 'CPU'}]
        
        try:
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    props = torch.cuda.get_device_properties(i)
                    memory_gb = props.total_memory / (1024**3)
                    label = f"CUDA:{i} - {props.name} ({memory_gb:.1f}GB)"
                    devices.append({'value': f'cuda:{i}', 'label': label})
        except Exception as e:
            print(f"Error detecting CUDA devices: {e}")
        
        return devices
    
    # Property schema for the properties panel
    @classmethod
    def get_properties(cls):
        """Dynamic properties with device detection."""
        return [
            {
                'name': 'model',
                'label': 'Model',
                'type': 'select',
                'options': [
                    {'value': 'yolov8n.pt', 'label': 'YOLOv8 Nano (fastest)'},
                    {'value': 'yolov8s.pt', 'label': 'YOLOv8 Small'},
                    {'value': 'yolov8m.pt', 'label': 'YOLOv8 Medium'},
                    {'value': 'yolov8l.pt', 'label': 'YOLOv8 Large'},
                    {'value': 'yolov8x.pt', 'label': 'YOLOv8 Extra Large (most accurate)'}
                ]
            },
            {
                'name': 'device',
                'label': 'Device',
                'type': 'select',
                'options': cls._get_device_options()
            },
            {
                'name': 'confidence',
                'label': 'Confidence Threshold',
                'type': 'text',
                'placeholder': '0.25'
            },
            {
                'name': 'iou',
                'label': 'IoU Threshold',
                'type': 'text',
                'placeholder': '0.45'
            },
            {
                'name': 'draw_results',
                'label': 'Draw Results on Image',
                'type': 'select',
                'options': [
                    {'value': 'true', 'label': 'Yes'},
                    {'value': 'false', 'label': 'No'}
                ]
            },
            {
                'name': 'max_det',
                'label': 'Max Detections',
                'type': 'text',
                'placeholder': '300'
            },
            {
                'name': 'include_image',
                'label': 'Include Image in Output',
                'type': 'checkbox',
                'default': True
            },
            {
                'name': 'include_predictions',
                'label': 'Include Predictions in Output',
                'type': 'checkbox',
                'default': True
            }
        ]
    
    properties = property(lambda self: self.get_properties())
    
    def __init__(self, node_id=None, name="yolo"):
        super().__init__(node_id, name)
        # Detect default device
        default_device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
        self.configure({
            'model': 'yolov8n.pt',
            'device': default_device,
            'confidence': '0.25',
            'iou': '0.45',
            'draw_results': 'true',
            'max_det': '300',
            'include_image': True,
            'include_predictions': True,
            'drop_messages': 'true'  # Enable by default for YOLO to prevent queue buildup
        })
        self.model = None
        self._model_loaded = False
    
    def _load_model(self):
        """Load the YOLO model (lazy loading on first use)."""
        if self._model_loaded:
            return
            
        try:
            from ultralytics import YOLO
            model_name = self.config.get('model', 'yolov8n.pt')
            device = self.config.get('device', 'cpu')
            self.model = YOLO(model_name)
            # Move model to specified device
            self.model.to(device)
            self._model_loaded = True
        except ImportError:
            error_msg = "ultralytics package not installed. Run: pip install ultralytics"
            self.report_error(error_msg)
            self.model = None
        except Exception as e:
            error_msg = f"Error loading model: {e}"
            self.report_error(error_msg)
            self.model = None
    
    def configure(self, config: Dict[str, Any]):
        """Override configure to reload model when model changes."""
        old_model = self.config.get('model') if hasattr(self, 'config') else None
        super().configure(config)
        new_model = self.config.get('model')
        
        # Reload model if it changed
        if old_model != new_model and old_model is not None:
            self._load_model()
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Process incoming image messages and perform YOLO inference.
        """
        # Lazy load model on first use
        if not self._model_loaded:
            self._load_model()
        
        if self.model is None:
            error_msg = "Model not loaded, skipping inference"
            self.report_error(error_msg)
            return
        
        # Get image from message
        payload = msg.get('payload')
        if payload is None:
            error_msg = "No image in payload"
            self.report_error(error_msg)
            return
        
        # Handle different image formats and track input format
        image = None
        input_format = None
        input_payload = payload
        
        # Standard format: look for image in payload.image first
        if isinstance(payload, dict) and 'image' in payload:
            input_payload = payload['image']
            payload = payload['image']
        
        # Camera node format: dict with 'format', 'encoding', 'data'
        if isinstance(payload, dict):
            
            img_format = payload.get('format')
            encoding = payload.get('encoding')
            data = payload.get('data')
            
            if img_format == 'jpeg' and encoding == 'base64':
                input_format = 'jpeg_base64_dict'
                try:
                    # Decode base64 JPEG
                    img_bytes = base64.b64decode(data)
                    nparr = np.frombuffer(img_bytes, np.uint8)
                    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                except Exception as e:
                    error_msg = f"Error decoding JPEG: {e}"
                    self.report_error(error_msg)
                    return
            elif img_format == 'bgr' and encoding == 'raw':
                input_format = 'bgr_raw_dict'
                try:
                    # Convert list back to numpy array
                    image = np.array(data, dtype=np.uint8)
                except Exception as e:
                    error_msg = f"Error converting raw BGR: {e}"
                    self.report_error(error_msg)
                    return
            elif img_format == 'bgr' and encoding == 'numpy':
                input_format = 'bgr_numpy_dict'
                # Direct numpy array from camera
                if isinstance(data, np.ndarray):
                    image = data
                else:
                    error_msg = f"Expected numpy array but got {type(data)}"
                    self.report_error(error_msg)
                    return
            else:
                error_msg = f"Unsupported format: {img_format}/{encoding}"
                self.report_error(error_msg)
                return
        
        # Direct base64 string
        elif isinstance(payload, str):
            input_format = 'base64_string'
            try:
                # Remove data URL prefix if present
                if payload.startswith('data:image'):
                    payload = payload.split(',')[1]
                
                # Decode base64
                img_bytes = base64.b64decode(payload)
                nparr = np.frombuffer(img_bytes, np.uint8)
                image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            except Exception as e:
                error_msg = f"Error decoding base64 string: {e}"
                self.report_error(error_msg)
                return
        
        # Direct numpy array
        elif isinstance(payload, np.ndarray):
            input_format = 'numpy_array'
            image = payload
        
        else:
            error_msg = f"Unsupported payload type: {type(payload)}"
            self.report_error(error_msg)
            return
        
        if image is None:
            error_msg = "Failed to decode image"
            self.report_error(error_msg)
            return
        
        try:
            # Get inference parameters
            confidence = float(self.config.get('confidence', '0.25'))
            iou = float(self.config.get('iou', '0.45'))
            max_det = int(self.config.get('max_det', '300'))
            draw_results = self.config.get('draw_results', 'true') == 'true'
            
            # Perform inference on specified device
            device = self.config.get('device', 'cpu')
            results = self.model.predict(
                image,
                conf=confidence,
                iou=iou,
                max_det=max_det,
                device=device,
                verbose=False
            )
            
            # Extract detection information
            detections = []
            if len(results) > 0:
                result = results[0]
                boxes = result.boxes
                
                if boxes is not None and len(boxes) > 0:
                    for i in range(len(boxes)):
                        box = boxes[i]
                        detection = {
                            'class_id': int(box.cls[0]),
                            'class_name': result.names[int(box.cls[0])],
                            'confidence': float(box.conf[0]),
                            'bbox': box.xyxy[0].cpu().numpy().tolist(),  # [x1, y1, x2, y2]
                        }
                        detections.append(detection)
            
            # Prepare output image
            output_image = image
            if draw_results and len(results) > 0:
                output_image = results[0].plot()
            
            # Encode image back to same format as input
            include_image = self.config.get('include_image', True)
            include_predictions = self.config.get('include_predictions', True)
            
            payload_out = {}
            
            if include_image:
                # Match output format to input format
                if input_format == 'jpeg_base64_dict':
                    # Encode as JPEG base64 dict (camera node format)
                    ret, buffer = cv2.imencode('.jpg', output_image)
                    if ret:
                        jpeg_base64 = base64.b64encode(buffer).decode('utf-8')
                        payload_out['image'] = {
                            'format': 'jpeg',
                            'encoding': 'base64',
                            'data': jpeg_base64,
                            'width': output_image.shape[1],
                            'height': output_image.shape[0]
                        }
                    else:
                        self.report_error("Failed to encode output image")
                        return
                        
                elif input_format == 'base64_string':
                    # Encode as direct base64 string
                    ret, buffer = cv2.imencode('.jpg', output_image)
                    if ret:
                        payload_out['image'] = base64.b64encode(buffer).decode('utf-8')
                    else:
                        self.report_error("Failed to encode output image")
                        return
                        
                elif input_format == 'numpy_array':
                    # Output as direct numpy array
                    payload_out['image'] = output_image
                    
                elif input_format == 'bgr_numpy_dict':
                    # Output as dict with numpy array
                    payload_out['image'] = {
                        'format': 'bgr',
                        'encoding': 'numpy',
                        'data': output_image,
                        'width': output_image.shape[1],
                        'height': output_image.shape[0]
                    }
                    
                elif input_format == 'bgr_raw_dict':
                    # Output as dict with raw list
                    payload_out['image'] = {
                        'format': 'bgr',
                        'encoding': 'raw',
                        'data': output_image.tolist(),
                        'width': output_image.shape[1],
                        'height': output_image.shape[0]
                    }
            
            # Always include detections and detection_count if include_predictions is True (for backward compatibility)
            if include_predictions or True:
                payload_out['detections'] = detections
                payload_out['detection_count'] = len(detections)
                
            output_msg = {
                'payload': payload_out,
                'topic': msg.get('topic', 'yolo')
            }
            
            # Send the message
            self.send(output_msg)
            
        except Exception as e:
            error_msg = f"Error during inference: {e}"
            self.report_error(error_msg)

