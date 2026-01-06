"""
Inference Node - Performs inference using multiple backends (Ultralytics, Geti, ONNX, etc.)
Supports engine selection, model file upload, target hardware selection, and inference.
"""

import base64
import cv2
import logging
import os
import numpy as np
from typing import Any, Dict, List, Optional
from pynode.nodes.base_node import BaseNode, Info

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text("Performs object detection and inference using multiple backends including Ultralytics YOLO, Intel Geti, and ONNX Runtime.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Image message with 'image' field (base64 or numpy array)"))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Detection results with optional annotated image"),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Engine Type:", "Select inference backend (Ultralytics, Geti, ONNX, etc.)"),
    ("Model File:", "Path to model file (.pt, .onnx, .xml, .zip)"),
    ("Target Hardware:", "CPU, CUDA GPU, or Intel OpenVINO devices"),
    ("Confidence:", "Minimum confidence threshold (0.0-1.0)"),
    ("IoU:", "IoU threshold for Non-Maximum Suppression"),
    ("Draw Results:", "Overlay detections on output image"),
)

# Try to import torch for device detection
try:
    import torch as _torch
    _HAS_TORCH = True
except ImportError:
    _torch = None  # type: ignore
    _HAS_TORCH = False


class InferenceNode(BaseNode):
    """
    Inference Node - performs inference using multiple backends.
    Supports Ultralytics YOLO, Geti, ONNX, and other inference engines.
    """
    # Visual properties
    display_name = 'Inference'
    info = str(_info)
    icon = '🧠'
    category = 'vision'
    color = '#7B68EE'  # Medium slate blue
    border_color = '#6A5ACD'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'engine_type': 'ultralytics',
        'model_path': '',
        'device': 'cpu',
        'confidence': '0.25',
        'iou': '0.45',
        'draw_results': 'true',
        'include_image': True,
        'include_predictions': True,
        'drop_messages': 'true'  # Enable by default to prevent queue buildup
    }
    
    @staticmethod
    def _get_available_engines() -> List[Dict[str, str]]:
        """Get available inference engines from the factory."""
        try:
            from pynode.nodes.InferenceNode.InferenceEngine.inference_engine_factory import InferenceEngineFactory
            engines = InferenceEngineFactory.get_available_engines_with_names()
            return [
                {'value': engine_type, 'label': display_name}
                for engine_type, display_name in engines.items()
            ]
        except Exception as e:
            logger.warning(f"Error getting available engines: {e}")
            # Fallback to common engines
            return [
                {'value': 'ultralytics', 'label': 'Ultralytics YOLO'},
                {'value': 'geti', 'label': 'Geti'},
                {'value': 'onnx', 'label': 'ONNX Runtime'},
                {'value': 'pass', 'label': 'Pass-through (Testing)'}
            ]
    
    @staticmethod
    def _get_device_options() -> List[Dict[str, str]]:
        """Get available hardware devices for inference."""
        devices = [
            {'value': 'cpu', 'label': 'CPU'},
        ]
        
        # Check for CUDA devices (NVIDIA GPUs)
        try:
            if _HAS_TORCH and _torch is not None and _torch.cuda.is_available():
                for i in range(_torch.cuda.device_count()):
                    props = _torch.cuda.get_device_properties(i)
                    memory_gb = props.total_memory / (1024**3)
                    label = f"CUDA:{i} - {props.name} ({memory_gb:.1f}GB)"
                    devices.append({'value': f'cuda:{i}', 'label': label})
        except Exception as e:
            logger.warning(f"Error detecting CUDA devices: {e}")
        
        # Add Intel OpenVINO devices
        devices.extend([
            {'value': 'intel:cpu', 'label': 'Intel CPU (OpenVINO)'},
            {'value': 'intel:gpu', 'label': 'Intel GPU (OpenVINO)'},
            {'value': 'intel:npu', 'label': 'Intel NPU (OpenVINO)'},
        ])
        
        return devices
    
    @classmethod
    def get_properties(cls):
        """Dynamic properties with engine and device detection."""
        return [
            {
                'name': 'engine_type',
                'label': 'Inference Engine',
                'type': 'select',
                'options': cls._get_available_engines(),
                'help': 'Select the inference backend to use'
            },
            {
                'name': 'model_path',
                'label': 'Model File',
                'type': 'file',
                'accept': '.pt,.onnx,.xml,.zip,.pth',
                'help': 'Upload or select a model file (.pt, .onnx, .xml, .zip)'
            },
            {
                'name': 'device',
                'label': 'Target Hardware',
                'type': 'select',
                'options': cls._get_device_options(),
                'help': 'Select target hardware for inference'
            },
            {
                'name': 'confidence',
                'label': 'Confidence Threshold',
                'type': 'text',
                'placeholder': '0.25',
                'help': 'Minimum confidence score for detections (0.0-1.0)'
            },
            {
                'name': 'iou',
                'label': 'IoU Threshold',
                'type': 'text',
                'placeholder': '0.45',
                'help': 'IoU threshold for Non-Maximum Suppression'
            },
            {
                'name': 'draw_results',
                'label': 'Draw Results on Image',
                'type': 'select',
                'options': [
                    {'value': 'true', 'label': 'Yes'},
                    {'value': 'false', 'label': 'No'}
                ],
                'help': 'Overlay detections on the output image'
            },
            {
                'name': 'include_image',
                'label': 'Include Image in Output',
                'type': 'checkbox',
                'default': True,
                'help': 'Include the processed image in output message'
            },
            {
                'name': 'include_predictions',
                'label': 'Include Predictions in Output',
                'type': 'checkbox',
                'default': True,
                'help': 'Include detection predictions in output message'
            }
        ]
    
    properties = property(lambda self: self.get_properties())
    # print(properties)
    
    @staticmethod
    def _get_default_device():
        """Get default device based on availability."""
        if _HAS_TORCH and _torch is not None and _torch.cuda.is_available():
            return 'cuda:0'
        return 'cpu'
    
    def __init__(self, node_id=None, name="Inference"):
        super().__init__(node_id, name)
        # Configure with defaults, then set device dynamically
        config = self.DEFAULT_CONFIG.copy()
        config['device'] = self._get_default_device()
        self.configure(config)
        
        # Engine state
        self.engine = None
        self._engine_loaded = False
        self._current_engine_type = None
        self._current_model_path = None
        self._current_device = None
    
    def _get_engine_factory(self):
        """Get the inference engine factory (lazy import)."""
        try:
            from pynode.nodes.InferenceNode.InferenceEngine.inference_engine_factory import InferenceEngineFactory
            return InferenceEngineFactory
        except ImportError as e:
            self.report_error(f"Failed to import InferenceEngineFactory: {e}")
            return None
    
    def _load_engine(self) -> bool:
        """Load or reload the inference engine based on current configuration."""
        engine_type = self.config.get('engine_type', 'ultralytics')
        model_path = self.config.get('model_path', '')
        device = self.config.get('device', 'cpu')
        
        # Check if we need to reload
        needs_reload = (
            not self._engine_loaded or
            engine_type != self._current_engine_type or
            model_path != self._current_model_path or
            device != self._current_device
        )
        
        if not needs_reload and self.engine is not None:
            return True
        
        # Validate model path
        if not model_path:
            # For some engines like ultralytics, allow auto-download of default models
            if engine_type == 'ultralytics':
                model_path = 'yolov8n.pt'  # Default to nano model
                self.config['model_path'] = model_path
            else:
                self.report_error("No model file specified")
                return False
        
        # Get the factory
        factory = self._get_engine_factory()
        if factory is None:
            return False
        
        try:
            # Create the engine instance
            logger.info(f"Creating {engine_type} engine with model: {model_path}, device: {device}")
            self.engine = factory.create(
                engine_type=engine_type,
                model_path=model_path,
                device=device
            )
            
            # Load the model
            if not self.engine.load(model_path, device):
                self.report_error(f"Failed to load model: {model_path}")
                self.engine = None
                self._engine_loaded = False
                return False
            
            # Update state
            self._engine_loaded = True
            self._current_engine_type = engine_type
            self._current_model_path = model_path
            self._current_device = device
            
            logger.info(f"Successfully loaded {engine_type} engine on {device}")
            return True
            
        except Exception as e:
            error_msg = f"Failed to create/load engine: {e}"
            logger.error(error_msg)
            self.report_error(error_msg)
            self.engine = None
            self._engine_loaded = False
            return False
    
    def configure(self, config: Dict[str, Any]):
        """Override configure to reload engine when configuration changes."""
        old_engine_type = self.config.get('engine_type') if hasattr(self, 'config') else None
        old_model_path = self.config.get('model_path') if hasattr(self, 'config') else None
        old_device = self.config.get('device') if hasattr(self, 'config') else None
        
        super().configure(config)
        
        new_engine_type = self.config.get('engine_type')
        new_model_path = self.config.get('model_path')
        new_device = self.config.get('device')
        
        # Check if engine-related config changed
        if (old_engine_type != new_engine_type or 
            old_model_path != new_model_path or 
            old_device != new_device):
            # Mark for reload on next inference
            if old_engine_type is not None:  # Only if not initial setup
                self._engine_loaded = False
    
    def get_engine_info(self) -> Dict[str, Any]:
        """Get information about the current engine state."""
        if self.engine is None:
            return {
                'loaded': False,
                'engine_type': self.config.get('engine_type'),
                'model_path': self.config.get('model_path'),
                'device': self.config.get('device')
            }
        
        info = self.engine.get_info()
        info['loaded'] = self._engine_loaded
        return info
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Process incoming image messages and perform inference.
        """
        # Lazy load engine on first use
        if not self._engine_loaded:
            if not self._load_engine():
                error_msg = "Engine not loaded, skipping inference"
                self.report_error(error_msg)
                return
        
        if self.engine is None:
            error_msg = "Engine not available, skipping inference"
            self.report_error(error_msg)
            return
        
        # Get image from message
        payload = msg.get('payload')
        if payload is None:
            error_msg = "No payload in message"
            self.report_error(error_msg)
            return
        
        # Decode image using base node helper
        image, input_format = self.decode_image(payload)
        
        if image is None or input_format is None:
            error_msg = "Failed to decode image from payload"
            self.report_error(error_msg)
            return
        
        try:
            # Perform inference
            results = self.engine.infer(image)
            
            # Check for inference errors
            if isinstance(results, dict) and results.get('success') is False:
                error_msg = f"Inference failed: {results.get('error', 'Unknown error')}"
                self.report_error(error_msg)
                return
            
            # Get configuration options
            draw_results = self.get_config_bool('draw_results', True)
            include_image = self.config.get('include_image', True)
            include_predictions = self.config.get('include_predictions', True)
            
            # Prepare output image
            output_image = image
            if draw_results:
                try:
                    output_image = self.engine.draw(image.copy(), results)
                except Exception as e:
                    logger.warning(f"Failed to draw results: {e}")
                    output_image = image
            
            # Convert results to JSON format
            try:
                json_results = self.engine.result_to_json(results, output_format="dict")
            except Exception as e:
                logger.warning(f"Failed to convert results to JSON: {e}")
                json_results = {"predictions": [], "num_detections": 0}
            
            # Build output payload
            payload_out = {}
            
            if include_image:
                # Encode image back to same format as input using base node helper
                encoded_image = self.encode_image(output_image, input_format)
                if encoded_image is not None:
                    payload_out['image'] = encoded_image
                else:
                    self.report_error("Failed to encode output image")
                    return
            
            if include_predictions:
                # Extract predictions from json_results
                if isinstance(json_results, dict):
                    payload_out['detections'] = json_results.get('predictions', [])
                    payload_out['detection_count'] = json_results.get('num_detections', 0)
                    payload_out['task_type'] = json_results.get('task_type', 'detect')
                    payload_out['bbox_format'] = 'xyxy'
                else:
                    payload_out['detections'] = []
                    payload_out['detection_count'] = 0
            
            # Add engine info to payload
            payload_out['engine_type'] = self._current_engine_type
            payload_out['device'] = self._current_device
            
            # Preserve original message properties and update payload
            msg['payload'] = payload_out
            msg['topic'] = msg.get('topic', 'inference')
            
            # Send the message
            self.send(msg)
            
        except Exception as e:
            import traceback
            error_msg = f"Error during inference: {e}\n{traceback.format_exc()}"
            logger.error(error_msg)
            self.report_error(f"Error during inference: {e}")
    
    def on_stop(self):
        """Clean up resources when node is stopped."""
        super().on_stop()
        self.engine = None
        self._engine_loaded = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize node to dictionary for API/storage."""
        data = super().to_dict()
        data['engineInfo'] = self.get_engine_info()
        return data


# API endpoint handlers for model management
def handle_model_upload(node: InferenceNode, file_data: bytes, filename: str) -> Dict[str, Any]:
    """
    Handle model file upload for the inference node.
    
    Args:
        node: The InferenceNode instance
        file_data: Raw bytes of the uploaded file
        filename: Original filename
        
    Returns:
        Dict with status and model path
    """
    try:
        # Create models directory if it doesn't exist
        models_dir = os.path.join(os.path.dirname(__file__), 'models')
        os.makedirs(models_dir, exist_ok=True)
        
        # Save the model file
        model_path = os.path.join(models_dir, filename)
        with open(model_path, 'wb') as f:
            f.write(file_data)
        
        # Update node configuration
        node.configure({'model_path': model_path})
        
        return {
            'success': True,
            'model_path': model_path,
            'filename': filename
        }
        
    except Exception as e:
        logger.error(f"Failed to upload model: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def get_available_models(models_dir: Optional[str] = None) -> List[Dict[str, str]]:
    """
    Get list of available model files.
    
    Args:
        models_dir: Directory to scan for models (default: node's models directory)
        
    Returns:
        List of dicts with model info
    """
    if models_dir is None:
        models_dir = os.path.join(os.path.dirname(__file__), 'models')
    
    models = []
    
    if os.path.exists(models_dir):
        valid_extensions = {'.pt', '.onnx', '.xml', '.zip', '.pth'}
        
        for filename in os.listdir(models_dir):
            ext = os.path.splitext(filename)[1].lower()
            if ext in valid_extensions:
                filepath = os.path.join(models_dir, filename)
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                models.append({
                    'filename': filename,
                    'path': filepath,
                    'extension': ext,
                    'size_mb': round(size_mb, 2)
                })
    
    return models
