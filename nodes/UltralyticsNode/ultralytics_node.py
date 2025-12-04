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
        
        # Decode image using base node helper
        image, input_format = self.decode_image(payload)
        
        if image is None or input_format is None:
            error_msg = "Failed to decode image from payload"
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
                # Encode image back to same format as input using base node helper
                encoded_image = self.encode_image(output_image, input_format)
                if encoded_image is not None:
                    payload_out['image'] = encoded_image
                else:
                    self.report_error("Failed to encode output image")
                    return
            
            # Always include detections and detection_count if include_predictions is True (for backward compatibility)
            if include_predictions or True:
                payload_out['detections'] = detections
                payload_out['detection_count'] = len(detections)
            
            # Preserve original message properties (like frame_count) and update payload
            # Note: send() handles deep copying, so we modify msg directly
            msg['payload'] = payload_out
            msg['topic'] = msg.get('topic', 'yolo')
            
            # Send the message
            self.send(msg)
            
        except Exception as e:
            error_msg = f"Error during inference: {e}"
            self.report_error(error_msg)

