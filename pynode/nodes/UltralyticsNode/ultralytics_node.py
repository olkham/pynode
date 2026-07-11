"""
Ultralytics YOLO node - performs object detection on images.
Supports YOLO26, YOLO11, YOLOv8 and other YOLO models.
Receives image data from camera nodes and outputs inference results.
"""

import logging
import os
from typing import Any, Dict, List
from pynode.nodes.base_node import BaseNode, Info, MessageKeys
import torch

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text("Performs YOLO object detection on input images using Ultralytics (YOLO26, YOLO11, YOLOv8, etc.).")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Image (base64 encoded)"))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Detection results with:"),
)
_info.add_bullets(
    ("payload.image:", "Annotated image (if draw_results enabled)"),
    ("payload.detections:", "List of detections with class_id, class_name, confidence, bbox"),
    ("payload.detection_count:", "Number of detected objects"),
    ("payload.bbox_format:", "Bounding box format (xyxy)"),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Model:", "YOLO variant (YOLO26, YOLO11, YOLOv8 - nano to extra large)"),
    ("Device:", "CPU, CUDA GPU, or Intel OpenVINO device for inference"),
    ("Confidence:", "Detection confidence threshold"),
    ("IoU:", "Intersection over Union threshold for NMS"),
)


class UltralyticsNode(BaseNode):
    """
    Ultralytics YOLO node - performs object detection inference.
    Supports YOLO26, YOLO11, YOLOv8 and other YOLO models.
    Receives images and outputs detection results with optional visualization.
    """
    # Visual properties
    display_name = 'YOLO'
    info = str(_info)
    icon = '🎯'
    category = 'vision'
    color = '#00D9FF'
    border_color = '#00A8CC'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'model': 'yolo26n.pt',
        'confidence': '0.25',
        'iou': '0.45',
        'draw_results': 'true',
        'max_det': '300',
        'include_image': True,
        'include_predictions': True,
        'drop_messages': 'true'  # Enable by default for YOLO to prevent queue buildup
    }
    
    @staticmethod
    def _get_device_options() -> List[Dict[str, str]]:
        """Get available hardware devices (CPU, CUDA, Intel OpenVINO) for the dropdown."""
        devices = [{'value': 'cpu', 'label': 'CPU'}]

        try:
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    props = torch.cuda.get_device_properties(i)
                    memory_gb = props.total_memory / (1024**3)
                    label = f"CUDA:{i} - {props.name} ({memory_gb:.1f}GB)"
                    devices.append({'value': f'cuda:{i}', 'label': label})
        except Exception as e:
            logger.warning(f"Error detecting CUDA devices: {e}")

        # Add Intel OpenVINO devices (enumerated via openvino when available;
        # falls back to the static CPU/GPU/NPU list otherwise)
        try:
            from pynode.nodes.InferenceNode.InferenceEngine.device_detection import (
                get_intel_device_options,
            )
            devices.extend(get_intel_device_options())
        except Exception as e:
            logger.warning(f"Error detecting Intel OpenVINO devices: {e}")
            devices.extend([
                {'value': 'intel:cpu', 'label': 'Intel CPU (OpenVINO)'},
                {'value': 'intel:gpu', 'label': 'Intel GPU (OpenVINO)'},
                {'value': 'intel:npu', 'label': 'Intel NPU (OpenVINO)'},
            ])

        return devices

    def _resolve_configured_device(self) -> str:
        """Return the configured device with plain 'intel:gpu' resolved to the
        first detected GPU (e.g. 'intel:gpu.0') so OpenVINO targets a real
        device instead of falling back to AUTO on multi-GPU systems."""
        device = self.config.get('device', 'cpu')
        try:
            from pynode.nodes.InferenceNode.InferenceEngine.device_detection import (
                resolve_intel_device,
            )
            return resolve_intel_device(device)
        except Exception:
            return device
    
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
                    {'value': 'yolo26n.pt', 'label': 'YOLO26 Nano (fastest, recommended)'},
                    {'value': 'yolo26s.pt', 'label': 'YOLO26 Small'},
                    {'value': 'yolo26m.pt', 'label': 'YOLO26 Medium'},
                    {'value': 'yolo26l.pt', 'label': 'YOLO26 Large'},
                    {'value': 'yolo26x.pt', 'label': 'YOLO26 Extra Large (most accurate)'},
                    {'value': 'yolo11n.pt', 'label': 'YOLO11 Nano'},
                    {'value': 'yolo11s.pt', 'label': 'YOLO11 Small'},
                    {'value': 'yolo11m.pt', 'label': 'YOLO11 Medium'},
                    {'value': 'yolo11l.pt', 'label': 'YOLO11 Large'},
                    {'value': 'yolo11x.pt', 'label': 'YOLO11 Extra Large'},
                    {'value': 'yolov8n.pt', 'label': 'YOLOv8 Nano (legacy)'},
                    {'value': 'yolov8s.pt', 'label': 'YOLOv8 Small (legacy)'},
                    {'value': 'yolov8m.pt', 'label': 'YOLOv8 Medium (legacy)'},
                    {'value': 'yolov8l.pt', 'label': 'YOLOv8 Large (legacy)'},
                    {'value': 'yolov8x.pt', 'label': 'YOLOv8 Extra Large (legacy)'}
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
    
    @staticmethod
    def _get_default_device():
        """Get default device based on availability."""
        return 'cuda:0' if torch.cuda.is_available() else 'cpu'
    
    def __init__(self, node_id=None, name="yolo"):
        super().__init__(node_id, name)
        # Configure with defaults, then set device dynamically
        config = self.DEFAULT_CONFIG.copy()
        config['device'] = self._get_default_device()
        self.configure(config)
        self.model = None
        self._model_loaded = False
    
    def _load_model(self):
        """Load the YOLO model (lazy loading on first use)."""
        if self._model_loaded:
            return
            
        try:
            from ultralytics import YOLO # type: ignore
            model_name = self.config.get('model', 'yolov8n.pt')
            device = self._resolve_configured_device()

            if isinstance(device, str) and device.lower().startswith('intel:'):
                # Intel OpenVINO path: torch's model.to() does not understand
                # 'intel:*' device strings, so export the model to OpenVINO
                # format once and load the exported model instead. The
                # resolved 'intel:gpu.N' string is passed to predict() at
                # inference time; ultralytics maps it to the OpenVINO device
                # name (e.g. intel:gpu.0 -> GPU.0).
                base_model = YOLO(model_name)
                source_path = str(getattr(base_model, 'ckpt_path', None) or model_name)
                openvino_model_path = os.path.splitext(source_path)[0] + '_openvino_model'
                if not os.path.isdir(openvino_model_path):
                    logger.info(f"Exporting {model_name} to OpenVINO format: {openvino_model_path}")
                    openvino_model_path = base_model.export(format='openvino')
                self.model = YOLO(openvino_model_path, task=base_model.task)
                logger.info(
                    f"Loaded OpenVINO model from {openvino_model_path} "
                    f"targeting device: {device}"
                )
            else:
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
        """Override configure to reload the model when model or device changes."""
        old_model = self.config.get('model') if hasattr(self, 'config') else None
        old_device = self.config.get('device') if hasattr(self, 'config') else None
        super().configure(config)

        # Mark for lazy reload on next inference if model or device changed.
        # (The previous code called _load_model() directly, which no-ops while
        # _model_loaded is True - so model changes never actually reloaded.)
        if old_model is not None and (
            old_model != self.config.get('model') or
            old_device != self.config.get('device')
        ):
            self._model_loaded = False
    
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
        payload = msg.get(MessageKeys.PAYLOAD)
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
            confidence = self.get_config_float('confidence', 0.25)
            iou = self.get_config_float('iou', 0.45)
            max_det = self.get_config_int('max_det', 300)
            draw_results = self.get_config_bool('draw_results', True)
            
            # Perform inference on specified device ('intel:gpu' resolved to
            # the first detected GPU, e.g. 'intel:gpu.0')
            device = self._resolve_configured_device()
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
                            'bbox_format': 'xyxy'
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
                    payload_out[MessageKeys.IMAGE.PATH] = encoded_image
                else:
                    self.report_error("Failed to encode output image")
                    return
            
            # Always include detections and detection_count if include_predictions is True (for backward compatibility)
            if include_predictions or True:
                payload_out['detections'] = detections
                payload_out['detection_count'] = len(detections)
                payload_out['bbox_format'] = 'xyxy'  # Document the bbox format at payload level
            
            # Preserve original message properties (like frame_count) and update payload
            # Note: send() handles deep copying, so we modify msg directly
            msg[MessageKeys.PAYLOAD] = payload_out
            msg[MessageKeys.TOPIC] = msg.get(MessageKeys.TOPIC, 'yolo')
            
            # Send the message
            self.send(msg)
            
        except Exception as e:
            error_msg = f"Error during inference: {e}"
            self.report_error(error_msg)

