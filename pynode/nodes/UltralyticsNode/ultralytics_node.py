"""
Ultralytics YOLO node - performs object detection on images.
Supports YOLO26, YOLO11, YOLOv8 and other YOLO models.
Receives image data from camera nodes and outputs inference results.
"""

import logging
import os
from typing import Any, Dict, List, Optional
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
    ("Device:", "CPU or CUDA GPU for inference"),
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
        # 'export_format': 'none'
    }
    
    @staticmethod
    def _detect_openvino_devices() -> List[Dict[str, str]]:
        """Detect available Intel OpenVINO devices (GPU, NPU)."""
        devices = []

        try:
            import openvino as ov
            core = ov.Core()
            available = core.available_devices  # Property, not method

            # Parse available devices
            for device in available:

                if device == 'CPU':
                    device_name = core.get_property(device, "FULL_DEVICE_NAME")
                    if 'INTEL' in device_name.upper():
                        devices.append({
                            'value': 'intel:cpu',
                            'label': 'Intel CPU (OpenVINO)'
                        })

                if device.startswith('GPU'):
                    # Get device properties and filter out non-Intel GPUs
                    try:
                        device_name = core.get_property(device, "FULL_DEVICE_NAME")
                        # Skip NVIDIA, AMD, and other non-Intel GPUs
                        if any(vendor in device_name.upper() for vendor in ['NVIDIA', 'AMD', 'RADEON', 'GEFORCE', 'RTX', 'GTX']):
                            logger.debug(f"Skipping non-Intel GPU from OpenVINO: {device_name}")
                            continue
                        # Only include Intel GPUs
                        if 'INTEL' in device_name.upper() or 'IRIS' in device_name.upper() or 'UHD' in device_name.upper():
                            devices.append({
                                'value': f'intel:{device.lower()}',  # e.g., intel:gpu.0
                                'label': f'Intel {device_name} (OpenVINO)'
                            })
                    except:
                        # If we can't get device name, skip it to be safe
                        logger.debug(f"Could not get device name for {device}, skipping")
                        pass
                elif device == 'NPU':
                    devices.append({
                        'value': 'intel:npu',
                        'label': 'Intel NPU (OpenVINO)'
                    })
        except ImportError:
            logger.info("OpenVINO not installed, skipping Intel device detection")
        except Exception as e:
            logger.warning(f"Error detecting OpenVINO devices: {e}")

        # If there is only one Intel GPU device, rename its value from 'intel:gpu.0' to 'intel:gpu'
        gpu_devices = [d for d in devices if d['value'].startswith('intel:gpu')]
        if len(gpu_devices) == 1 and gpu_devices[0]['value'] == 'intel:gpu.0':
            gpu_devices[0]['value'] = 'intel:gpu'

        return devices

    @staticmethod
    def _get_device_options() -> List[Dict[str, str]]:
        """Get available devices including auto-detected Intel hardware."""
        devices = [{'value': 'cpu', 'label': 'CPU'}]

        # CUDA devices (auto-detected)
        try:
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    props = torch.cuda.get_device_properties(i)
                    memory_gb = props.total_memory / (1024**3)
                    label = f"CUDA:{i} - {props.name} ({memory_gb:.1f}GB)"
                    devices.append({'value': f'cuda:{i}', 'label': label})
        except Exception as e:
            logger.warning(f"Error detecting CUDA devices: {e}")

        # Intel OpenVINO devices (auto-detected)
        openvino_devices = UltralyticsNode._detect_openvino_devices()
        if openvino_devices:
            devices.extend(openvino_devices)
        else:
            # Fallback to generic options if detection fails
            devices.extend([
                {'value': 'intel:cpu', 'label': 'Intel CPU (OpenVINO)'},
                {'value': 'intel:gpu', 'label': 'Intel GPU (OpenVINO)'},
                {'value': 'intel:npu', 'label': 'Intel NPU (OpenVINO)'},
                {'value': 'intel:auto', 'label': 'Intel Auto'},
            ])

        # Custom option
        devices.append({'value': '__custom__', 'label': '⚙️ Custom device string...'})

        return devices

    @staticmethod
    def _get_uploaded_models() -> List[Dict[str, str]]:
        """Scan models directory for custom uploaded .pt files."""
        models_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'models')
        if not os.path.exists(models_dir):
            return []

        uploaded = []
        for filename in os.listdir(models_dir):
            if filename.endswith('.pt'):
                filepath = os.path.join(models_dir, filename)
                uploaded.append({
                    'value': filepath,
                    'label': f"📁 {filename}"
                })
        return uploaded

    @staticmethod
    def _validate_device_string(device: str) -> bool:
        """Validate device string format."""
        if not device or not isinstance(device, str):
            return False

        device = device.lower().strip()

        # Valid patterns:
        # - cpu
        # - cuda, cuda:0, cuda:1, etc.
        # - intel:cpu, intel:gpu, intel:npu
        # - intel:gpu.0, intel:gpu.1 (with dots for OpenVINO device indices)
        # - intel:npu, intel:npu.0, etc.

        if device == 'cpu':
            return True

        if device.startswith('cuda'):
            # cuda or cuda:N where N is a number
            if device == 'cuda':
                return True
            if ':' in device:
                parts = device.split(':')
                return len(parts) == 2 and parts[0] == 'cuda'
            return False

        if device.startswith('intel:'):
            # intel:cpu, intel:gpu, intel:npu, intel:gpu.0, intel:npu.0, etc.
            intel_part = device[6:]  # Remove 'intel:' prefix
            if intel_part in ['cpu', 'gpu', 'npu']:
                return True
            # Check for device with index (gpu.0, npu.0, etc.)
            if '.' in intel_part or ':' in intel_part:
                # Allow patterns like gpu.0, gpu:0, npu.0, etc.
                return True
            return False

        return False
    
    # Property schema for the properties panel
    @classmethod
    def get_properties(cls):
        """Dynamic properties with device detection."""
        # Build model options with built-in + uploaded models
        builtin_models = [
            # Detection models
            {'value': 'yolo26n.pt', 'label': 'YOLO26 Nano (Detection)'},
            {'value': 'yolo26s.pt', 'label': 'YOLO26 Small (Detection)'},
            {'value': 'yolo26m.pt', 'label': 'YOLO26 Medium (Detection)'},
            {'value': 'yolo26l.pt', 'label': 'YOLO26 Large (Detection)'},
            {'value': 'yolo26x.pt', 'label': 'YOLO26 Extra Large (Detection)'},

            # Segmentation models
            {'value': 'yolo26n-seg.pt', 'label': 'YOLO26 Nano (Segmentation)'},
            {'value': 'yolo26s-seg.pt', 'label': 'YOLO26 Small (Segmentation)'},
            {'value': 'yolo26m-seg.pt', 'label': 'YOLO26 Medium (Segmentation)'},
            {'value': 'yolo26l-seg.pt', 'label': 'YOLO26 Large (Segmentation)'},
            {'value': 'yolo26x-seg.pt', 'label': 'YOLO26 Extra Large (Segmentation)'},

            # Pose estimation models
            {'value': 'yolo26n-pose.pt', 'label': 'YOLO26 Nano (Pose)'},
            {'value': 'yolo26s-pose.pt', 'label': 'YOLO26 Small (Pose)'},
            {'value': 'yolo26m-pose.pt', 'label': 'YOLO26 Medium (Pose)'},
            {'value': 'yolo26l-pose.pt', 'label': 'YOLO26 Large (Pose)'},
            {'value': 'yolo26x-pose.pt', 'label': 'YOLO26 Extra Large (Pose)'},

            # Oriented bounding box models
            {'value': 'yolo26n-obb.pt', 'label': 'YOLO26 Nano (OBB)'},
            {'value': 'yolo26s-obb.pt', 'label': 'YOLO26 Small (OBB)'},
            {'value': 'yolo26m-obb.pt', 'label': 'YOLO26 Medium (OBB)'},
            {'value': 'yolo26l-obb.pt', 'label': 'YOLO26 Large (OBB)'},
            {'value': 'yolo26x-obb.pt', 'label': 'YOLO26 Extra Large (OBB)'},

            # Classification models
            {'value': 'yolo26n-cls.pt', 'label': 'YOLO26 Nano (Classification)'},
            {'value': 'yolo26s-cls.pt', 'label': 'YOLO26 Small (Classification)'},
            {'value': 'yolo26m-cls.pt', 'label': 'YOLO26 Medium (Classification)'},
            {'value': 'yolo26l-cls.pt', 'label': 'YOLO26 Large (Classification)'},
            {'value': 'yolo26x-cls.pt', 'label': 'YOLO26 Extra Large (Classification)'},

            # YOLO11 models
            {'value': 'yolo11n.pt', 'label': 'YOLO11 Nano'},
            {'value': 'yolo11s.pt', 'label': 'YOLO11 Small'},
            {'value': 'yolo11m.pt', 'label': 'YOLO11 Medium'},
            {'value': 'yolo11l.pt', 'label': 'YOLO11 Large'},
            {'value': 'yolo11x.pt', 'label': 'YOLO11 Extra Large'},

            # YOLOv8 models (legacy)
            {'value': 'yolov8n.pt', 'label': 'YOLOv8 Nano (legacy)'},
            {'value': 'yolov8s.pt', 'label': 'YOLOv8 Small (legacy)'},
            {'value': 'yolov8m.pt', 'label': 'YOLOv8 Medium (legacy)'},
            {'value': 'yolov8l.pt', 'label': 'YOLOv8 Large (legacy)'},
            {'value': 'yolov8x.pt', 'label': 'YOLOv8 Extra Large (legacy)'}
        ]

        uploaded_models = cls._get_uploaded_models()
        model_options = builtin_models.copy()
        if uploaded_models:
            model_options.append({'value': '', 'label': '─── 📁 Custom Models ───', 'disabled': True})
            model_options.extend(uploaded_models)
            model_options.append({'value': '__upload__', 'label': '📤 Upload New Model...'})

        return [
            {
                'name': 'model',
                'label': 'Model',
                'type': 'select',
                'options': model_options
            },
            {
                'name': 'model_file',
                'label': 'Upload Custom Model',
                'type': 'file',
                'accept': '.pt',
                'help': 'Upload a custom trained YOLO .pt model file',
                'showIf': {'model': ['__upload__'] + ([m['value'] for m in uploaded_models] if uploaded_models else [])}
            },
            {
                'name': 'device',
                'label': 'Device',
                'type': 'select',
                'options': cls._get_device_options()
            },
            {
                'name': 'device_custom',
                'label': 'Custom Device String',
                'type': 'text',
                'placeholder': 'e.g., intel:gpu:2, cuda:1',
                'help': 'Enter custom device string when "Custom" is selected',
                'showIf': {'device': '__custom__'}
            },
            # {
            #     'name': 'export_format',
            #     'label': 'Export Model (Optional)',
            #     'type': 'select',
            #     'options': [
            #         {'value': 'none', 'label': 'No Export (use .pt directly)'},
            #         {'value': 'engine', 'label': 'TensorRT (.engine) - For NVIDIA GPU only'},
            #         {'value': 'openvino', 'label': 'OpenVINO - For Intel CPU/GPU/NPU only'},
            #         {'value': 'onnx', 'label': 'ONNX (.onnx) - Universal'},
            #         {'value': 'torchscript', 'label': 'TorchScript (.torchscript) - Universal'},
            #     ],
            #     'help': 'Create optimized model file for deployment. Select format matching your device: TensorRT for NVIDIA GPUs, OpenVINO for Intel hardware, ONNX/TorchScript for any device. Intel devices auto-export to OpenVINO. Additional packages may be required (see requirements.txt)'
            # },
            # {
            #     'name': 'export_half',
            #     'label': 'FP16 Precision (Export)',
            #     'type': 'checkbox',
            #     'default': False,
            #     'help': 'Use half-precision (FP16) in exported model for faster inference with lower memory usage',
            #     'showIf': {'export_format': ['engine', 'openvino', 'onnx']}
            # },
            # {
            #     'name': 'export_int8',
            #     'label': 'INT8 Quantization (Export)',
            #     'type': 'checkbox',
            #     'default': False,
            #     'help': 'Use INT8 quantization in exported model for maximum speed (may require calibration data)',
            #     'showIf': {'export_format': ['engine']}
            # },
            # {
            #     'name': 'export_batch',
            #     'label': 'Batch Size (Export)',
            #     'type': 'text',
            #     'placeholder': '1',
            #     'help': 'Maximum batch size for exported model (affects memory usage)',
            #     'showIf': {'export_format': ['engine', 'onnx']}
            # },
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

    def _get_exported_model_path(self, model_path: str, format_type: str) -> Optional[str]:
        """Check if exported model already exists."""
        base_path = os.path.splitext(model_path)[0]

        if format_type == 'engine':
            expected_path = f"{base_path}.engine"
        elif format_type == 'openvino':
            expected_path = f"{base_path}_openvino_model"
        elif format_type == 'onnx':
            expected_path = f"{base_path}.onnx"
        elif format_type == 'torchscript':
            expected_path = f"{base_path}.torchscript"
        else:
            return None

        if os.path.exists(expected_path):
            return expected_path
        return None

    def _export_model(self, model, model_path: str, format_type: str) -> Optional[str]:
        """
        Export model to specified format with caching.

        Args:
            model: Loaded YOLO model
            model_path: Original model path
            format_type: Export format (engine, openvino, onnx, etc.)

        Returns:
            Path to exported model or None if export fails
        """
        if format_type == 'none':
            return None

        # Check if export already exists
        existing_export = self._get_exported_model_path(model_path, format_type)
        if existing_export:
            logger.info(f"Using cached exported model: {existing_export}")
            return existing_export

        try:
            # Get export parameters
            half = self.get_config_bool('export_half', False)
            int8 = self.get_config_bool('export_int8', False)
            batch = self.get_config_int('export_batch', 1)

            logger.info(f"Exporting model to {format_type} format...")

            # Perform export
            export_kwargs = {
                'format': format_type,
                'half': half,
                'batch': batch
            }

            # Add INT8 for TensorRT
            if format_type == 'engine' and int8:
                export_kwargs['int8'] = True

            # For OpenVINO, pass device from config if it's an Intel device
            if format_type == 'openvino':
                device = self.config.get('device', 'cpu')
                if device.startswith('intel:'):
                    # OpenVINO expects device format like "GPU.0" or "NPU"
                    ov_device = device.replace('intel:', '').upper()
                    export_kwargs['device'] = ov_device
                    logger.info(f"Exporting OpenVINO model for device: {ov_device}")

            # Export the model
            exported_path = model.export(**export_kwargs)

            logger.info(f"Model exported successfully to: {exported_path}")
            return str(exported_path)

        except Exception as e:
            logger.error(f"Failed to export model: {e}")
            self.report_error(f"Model export failed: {e}")
            return None

    def _load_model(self):
        """Load the YOLO model with optional export."""
        if self._model_loaded:
            return

        try:
            from ultralytics import YOLO # type: ignore
            model_name = self.config.get('model', 'yolo26n.pt')

            # Handle custom uploaded models
            if os.path.isabs(model_name) or os.path.exists(model_name):
                model_path = model_name  # Custom uploaded model (full path)
            else:
                model_path = model_name  # Built-in model name

            # Get device with custom override
            device = self.config.get('device', 'cpu')
            if device == '__custom__':
                device = self.config.get('device_custom', 'cpu').strip()
                if not device:
                    device = 'cpu'
                    logger.warning("Custom device was empty, falling back to CPU")

            # Validate device string
            if not self._validate_device_string(device):
                logger.warning(f"Invalid device string '{device}', falling back to CPU")
                device = 'cpu'

            # Load base model
            self.model = YOLO(model_path)

            # Validate export format against selected device
            export_format = self.config.get('export_format', 'none')

            # Check for incompatible export/device combinations
            if export_format == 'engine' and not device.startswith('cuda'):
                logger.warning(f"TensorRT export selected but device is '{device}'. TensorRT requires NVIDIA GPU (cuda). Skipping export.")
                export_format = 'none'
            elif export_format == 'openvino' and device.startswith('cuda'):
                logger.warning(f"OpenVINO export selected but device is '{device}'. OpenVINO is for Intel hardware. Consider using TensorRT or ONNX instead. Skipping export.")
                export_format = 'none'

            # Auto-export to OpenVINO if Intel device is selected
            if device.startswith('intel:') and export_format == 'none':
                logger.info(f"Intel device '{device}' selected, auto-exporting to OpenVINO format")
                export_format = 'openvino'

            # Export if requested (but don't reload exported model)
            if export_format != 'none':
                exported_path = self._export_model(self.model, model_path, export_format)
                if exported_path:
                    logger.info(f"✓ Model exported to: {exported_path}")
                    logger.info(f"Note: Exported model saved for deployment. Using original .pt model for inference.")
                    # Note: Exported models (.engine, .onnx, etc.) are for deployment/distribution.
                    # We continue using the original .pt model for inference in this session because:
                    # 1. .pt models are more flexible and support all YOLO operations
                    # 2. Exported formats may have limitations (e.g., .engine is device-specific)
                    # 3. This allows users to create deployment artifacts without changing runtime behavior

            # Move to device (only for .pt models on CUDA/CPU)
            # Exported models (engine, onnx, openvino) handle device internally
            if export_format == 'none' and not device.startswith('intel:'):
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
        """Override configure to reload model when model/device/export changes."""
        old_model = self.config.get('model') if hasattr(self, 'config') else None
        old_device = self.config.get('device') if hasattr(self, 'config') else None
        old_export = self.config.get('export_format') if hasattr(self, 'config') else None

        super().configure(config)

        new_model = self.config.get('model')
        new_device = self.config.get('device')
        new_export = self.config.get('export_format')

        # Reload model if model, device, or export format changed
        if old_model is not None and (
            old_model != new_model or
            old_device != new_device or
            old_export != new_export
        ):
            self._model_loaded = False
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

            # Perform inference
            # For OpenVINO models (Intel devices), don't pass device to predict()
            # as the device is already set during export/loading
            device = self.config.get('device', 'cpu')
            predict_kwargs = {
                'conf': confidence,
                'iou': iou,
                'max_det': max_det,
                'verbose': False
            }

            # Only pass device for non-Intel devices (CUDA/CPU)
            if not device.startswith('intel:'):
                predict_kwargs['device'] = device

            results = self.model.predict(image, **predict_kwargs)
            
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

