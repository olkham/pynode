import sys
import os


# Add the project root to the path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
engines_dir = current_dir
inference_engine_dir = os.path.dirname(engines_dir)
project_root = os.path.dirname(inference_engine_dir)

# Add both the project root and the parent directory to sys.path
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if inference_engine_dir not in sys.path:
    sys.path.insert(0, inference_engine_dir)

import cv2
from flask import json
import numpy as np
from typing import Any, Dict, Optional

# Handle both standalone and module imports
try:
    from .base_engine import BaseInferenceEngine
except ImportError:
    # If running as standalone script, try absolute import
    try:
        from InferenceEngine.engines.base_engine import BaseInferenceEngine
    except ImportError:
        # Last resort - direct import from the same directory
        from base_engine import BaseInferenceEngine


from ultralytics import YOLO

class UltralyticsEngine(BaseInferenceEngine):
    """Inference engine for Ultralytics YOLO models"""
    
    # Define the user-friendly display name
    display_name = "Ultralytics YOLO"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model_path = kwargs.get('model_path', None)
        self.device = kwargs.get('device', "CPU")  # Default device
        self.output_format = kwargs.get('output_format', "geti")  # Default output format
        self.task = kwargs.get('task', 'detect')  # Default task for YOLO models
        self.deployment = None
        self.use_openvino = False
        self.openvino_model_path = None
        
        # Configure Ultralytics to be less verbose
        try:
            import ultralytics
            from ultralytics.utils import LOGGER
            
            # Set various verbosity controls
            ultralytics.checks.check_requirements = lambda x: None  # Disable requirements check output
            
            # Set Ultralytics logging to WARNING level to reduce verbosity
            import logging
            logging.getLogger("ultralytics").setLevel(logging.WARNING)
            LOGGER.setLevel(logging.WARNING)
            
            # Disable various verbose outputs
            import os
            os.environ['YOLO_VERBOSE'] = 'False'
            
        except:
            pass  # If ultralytics not available or other error, continue
        
        # Auto-detect Intel hardware and optimize device string
        self.device = self._optimize_device_for_intel(self.device)
    
    
    def _optimize_device_for_intel(self, device: str) -> str:
        """
        Optimize device string for Intel hardware.
        Converts device strings like 'GPU.0', 'GPU.1' to 'intel:gpu.0', 'intel:gpu.1' 
        when Intel hardware is detected.
        """
        if device is None:
            device = "CPU"
        
        device = device.upper()
        
        # Handle device indices (e.g., GPU.0, GPU.1, CPU.0)
        device_base = device
        device_index = ""
        if "." in device:
            device_parts = device.split(".", 1)
            device_base = device_parts[0]
            device_index = f".{device_parts[1]}"
        
        # Map device strings to Intel OpenVINO format
        device_mapping = {
            'CPU': 'intel:cpu',# if intel_hw['cpu'] else 'cpu',
            'GPU': 'intel:gpu',# if intel_hw['gpu'] else 'gpu', 
            'NPU': 'intel:npu',# if intel_hw['npu'] else 'npu'
        }
        
        # Check if device needs Intel prefix
        if device_base in device_mapping:
            optimized_device = device_mapping[device_base] + device_index
            if optimized_device.startswith('intel:'):
                self.use_openvino = True
            return optimized_device.lower()
        elif device.lower().startswith('intel:'):
            self.use_openvino = True
            return device.lower()
        else:
            return device.lower()
                
    def _load_model(self, model_file: str, device: str = "CPU") -> bool:

        if device is None:
            device = self.device

        if model_file is None:
            model_file = self.model_path

        if not self.check_valid_model(model_file):
            return False

        """Load YOLO model from file or download if not found"""
        try:
            # Validate CUDA device availability before using
            if device in ['cuda', '0', 'gpu'] or (isinstance(device, str) and device.isdigit()):
                try:
                    import torch
                    if not torch.cuda.is_available():
                        print(f"WARNING: CUDA device '{device}' requested but CUDA is not available. Falling back to CPU.")
                        device = 'cpu'
                        self.device = device
                except ImportError:
                    print(f"WARNING: PyTorch not available to check CUDA. Falling back to CPU for device '{device}'.")
                    device = 'cpu'
                    self.device = device

            # Set model path and load model
            self.model_path = model_file

            # Auto-detect task if not explicitly set or if default 'detect'
            if self.task == 'detect':
                detected_task = self._detect_model_task(model_file)
                if detected_task != 'detect':
                    print(f"Auto-detected model task: {detected_task}")
                    self.task = detected_task

            print(f"Loading model with task: {self.task}")
            
            # Check model compatibility before attempting to load
            is_compatible, compatibility_reason = self._check_model_compatibility(model_file)
            if not is_compatible:
                print(f"⚠️  COMPATIBILITY WARNING: {compatibility_reason}")
                if "YOLOv5" in compatibility_reason:
                    print("🔄 Will attempt to load anyway with fallback handling...")
                elif "does not exist" in compatibility_reason or "not readable" in compatibility_reason:
                    raise FileNotFoundError(f"Model file issue: {compatibility_reason}")
                else:
                    print("🔄 Will attempt to load anyway...")
            
            # First, try to load the model directly
            model_to_load = model_file
            try:
                # Check if we should use OpenVINO optimization
                if self.use_openvino or device.startswith('intel:'):
                    print(f"Using Intel OpenVINO optimization for device: {device}")
                    
                    # Load original model first with explicit task
                    self.model = YOLO(model_file, task=self.task)
                    
                    # Generate OpenVINO model path
                    model_name = os.path.splitext(os.path.basename(model_file))[0]
                    model_folder = os.path.dirname(model_file)
                    self.openvino_model_path = os.path.join(model_folder, f"{model_name}_openvino_model")
                    
                    # Export to OpenVINO format if not already exists
                    if not os.path.exists(self.openvino_model_path):
                        print(f"Exporting model to OpenVINO format: {self.openvino_model_path}")
                        self.model.export(format="openvino", name=model_name)
                    
                    # Load the OpenVINO model with explicit task
                    self.model = YOLO(self.openvino_model_path, task=self.task)
                    print(f"Loaded OpenVINO model from: {self.openvino_model_path}")
                else:
                    # Load regular PyTorch model with explicit task
                    self.model = YOLO(model_file, task=self.task)
                    print(f"Loaded PyTorch model: {model_file}")
                    
            except Exception as yolo_error:
                # Check if this is a YOLOv5 compatibility issue
                if "models.yolo" in str(yolo_error) or "ModuleNotFoundError" in str(yolo_error):
                    print(f"Detected YOLOv5 compatibility issue: {yolo_error}")
                    print("Attempting to convert YOLOv5 model to compatible format...")
                    
                    # Try to convert to ONNX format as a workaround
                    model_to_load = self._handle_yolov5_model(model_file)
                    if model_to_load and model_to_load != model_file:
                        print(f"Using converted model: {model_to_load}")
                        # Try loading the converted model
                        self.model = YOLO(model_to_load, task=self.task)
                        print(f"Successfully loaded converted model: {model_to_load}")
                    else:
                        # If conversion failed, re-raise the original error
                        raise yolo_error
                else:
                    # Re-raise other types of errors
                    raise yolo_error
            
            # Set device for inference
            self.device = device
            self.is_loaded = True
            return True
            
        except Exception as e:
            print(f"Failed to load model: {e}")
            
            # Provide specific guidance for YOLOv5 compatibility issues
            if "models.yolo" in str(e) or "ModuleNotFoundError" in str(e):
                self._show_yolov5_guidance(model_file)
            
            import traceback
            traceback.print_exc()
            return False

    def _show_yolov5_guidance(self, model_file: str):
        """Show helpful guidance for YOLOv5 compatibility issues"""
        print("\n" + "=" * 70)
        print("🚨 YOLOv5 COMPATIBILITY ISSUE DETECTED")
        print("=" * 70)
        print(f"The model '{os.path.basename(model_file)}' appears to be a YOLOv5 model")
        print("that is incompatible with the current Ultralytics package.")
        print()
        print("📋 RECOMMENDED SOLUTIONS (in order of preference):")
        print()
        print("1. 🎯 USE YOLOv8/YOLOv11 MODELS (BEST OPTION)")
        print("   • Download from: https://github.com/ultralytics/ultralytics")
        print("   • Models: yolov8n.pt, yolov8s.pt, yolov8m.pt, yolov8l.pt, yolov8x.pt")
        print("   • Or: yolo11n.pt, yolo11s.pt, yolo11m.pt, yolo11l.pt, yolo11x.pt")
        print()
        print("2. 🔄 CONVERT YOLOv5 TO ONNX FORMAT")
        print("   • Install YOLOv5: git clone https://github.com/ultralytics/yolov5")
        print("   • Navigate to YOLOv5 directory")
        print(f"   • Run: python export.py --weights '{model_file}' --include onnx")
        print("   • Use the generated .onnx file in InferNode")
        print()
        print("3. 🏋️ RETRAIN WITH ULTRALYTICS")
        print("   • Train a new model using the Ultralytics package")
        print("   • This ensures full compatibility")
        print()
        print("💡 QUICK FIXES:")
        print("   • Try downloading yolov8n.pt: it's small and compatible")
        print("   • Place it in your model repository folder")
        print("   • Create a new pipeline with the YOLOv8 model")
        print()
        print("📖 DETAILED GUIDE:")
        print("   See: docs/YOLOv5_COMPATIBILITY_GUIDE.md for complete instructions")
        print()
        print("ℹ️  For more help, visit: https://docs.ultralytics.com/")
        print("=" * 70)

    def _suggest_compatible_model(self, model_folder: str) -> str | None:
        """
        Suggest and optionally download a compatible YOLOv8 model as an alternative.
        """
        try:
            # Suggest YOLOv8n as a lightweight alternative
            suggested_models = ['yolov8n.pt', 'yolov8s.pt', 'yolo11n.pt']
            
            for model_name in suggested_models:
                model_path = os.path.join(model_folder, model_name)
                if os.path.exists(model_path):
                    print(f"✅ Found compatible model: {model_path}")
                    return model_path
            
            # If no compatible model found, suggest downloading one
            print("📥 Consider downloading a compatible model:")
            print("   Run this in Python:")
            print("   from ultralytics import YOLO")
            print("   model = YOLO('yolov8n.pt')  # This will auto-download")
            
            return None
            
        except Exception as e:
            print(f"Error suggesting compatible model: {e}")
            return None

    def _is_yolov5_model(self, model_file: str) -> bool:
        """
        Check if a model file is likely a YOLOv5 model that might cause compatibility issues.
        """
        try:
            import torch
            
            # Try to load and inspect the model checkpoint
            checkpoint = torch.load(model_file, map_location='cpu')
            
            # Check for YOLOv5 indicators
            if isinstance(checkpoint, dict):
                # Check for YOLOv5-specific keys
                if 'model' in checkpoint:
                    model = checkpoint['model']
                    # YOLOv5 models often have these characteristics
                    if hasattr(model, 'yaml') or hasattr(model, 'yaml_file'):
                        return True
                    if hasattr(model, 'names') and hasattr(model, 'stride'):
                        # Additional YOLOv5 indicators
                        if str(type(model)).find('yolov5') != -1:
                            return True
            
            return False
            
        except Exception:
            # If we can't inspect the model, assume it might be compatible
            return False

    def _handle_yolov5_model(self, model_file: str) -> str | None:
        """
        Handle YOLOv5 model compatibility issues by converting to ONNX format.
        Returns the path to the converted model or None if conversion fails.
        """
        try:
            import os
            import subprocess
            import tempfile
            
            # Generate ONNX model path
            model_name = os.path.splitext(os.path.basename(model_file))[0]
            model_folder = os.path.dirname(model_file)
            onnx_model_path = os.path.join(model_folder, f"{model_name}_converted.onnx")
            
            # Check if ONNX version already exists
            if os.path.exists(onnx_model_path):
                print(f"Found existing converted ONNX model: {onnx_model_path}")
                return onnx_model_path
            
            print(f"Converting YOLOv5 model to ONNX format...")
            
            # Try to use ultralytics export functionality with error handling
            try:
                # First, try to load with torch directly to get model structure
                import torch
                
                # Try loading with torch.load to inspect the model
                checkpoint = torch.load(model_file, map_location='cpu')
                
                # Check if this looks like a YOLOv5 model
                if 'model' in checkpoint and hasattr(checkpoint.get('model'), 'yaml'):
                    print("Detected YOLOv5 model structure")
                    
                    # Try to create a temporary script to convert using YOLOv5 export
                    yolov5_export_script = f"""
import sys
import os
import torch

# Try to set up minimal YOLOv5 environment
sys.path.insert(0, '{os.path.dirname(model_file)}')

try:
    # Method 1: Try direct ONNX export using torch
    import torch.onnx
    
    # Load the model
    checkpoint = torch.load('{model_file}', map_location='cpu')
    model = checkpoint['model']
    
    # Create dummy input
    dummy_input = torch.randn(1, 3, 640, 640)
    
    # Export to ONNX
    torch.onnx.export(
        model,
        dummy_input,
        '{onnx_model_path}',
        input_names=['input'],
        output_names=['output'],
        dynamic_axes={{'input': {{0: 'batch_size'}}, 'output': {{0: 'batch_size'}}}},
        opset_version=11
    )
    print("Successfully exported to ONNX using torch.onnx")
    
except Exception as e:
    print(f"Direct export failed: {{e}}")
    # Method 2: Try using ultralytics YOLO to export
    try:
        from ultralytics import YOLO
        # This might fail, but we'll try anyway
        temp_model = YOLO('{model_file}')
        temp_model.export(format='onnx', name='{model_name}_converted')
        print("Successfully exported using ultralytics")
    except Exception as e2:
        print(f"Ultralytics export also failed: {{e2}}")
        sys.exit(1)
"""
                    
                    # Write and execute the conversion script
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                        f.write(yolov5_export_script)
                        temp_script = f.name
                    
                    try:
                        # Execute the conversion script
                        result = subprocess.run([
                            'python', temp_script
                        ], capture_output=True, text=True, timeout=300)  # 5 minute timeout
                        
                        if result.returncode == 0:
                            print("Model conversion completed successfully")
                            if os.path.exists(onnx_model_path):
                                return onnx_model_path
                        else:
                            print(f"Conversion script failed: {result.stderr}")
                            
                    except subprocess.TimeoutExpired:
                        print("Model conversion timed out")
                    except Exception as script_error:
                        print(f"Error running conversion script: {script_error}")
                    finally:
                        # Clean up temporary script
                        try:
                            os.unlink(temp_script)
                        except:
                            pass
                            
            except Exception as torch_error:
                print(f"Could not analyze model with torch: {torch_error}")
            
            # If all conversion methods failed, provide helpful error message
            print("=" * 60)
            print("YOLOv5 MODEL COMPATIBILITY ISSUE DETECTED")
            print("=" * 60)
            print(f"The model '{model_file}' appears to be a YOLOv5 model that is")
            print("incompatible with the Ultralytics package.")
            print("")
            print("SOLUTIONS:")
            print("1. Use a YOLOv8/YOLOv11 model instead (recommended)")
            print("2. Convert your YOLOv5 model to ONNX format manually:")
            print("   - Clone YOLOv5 repo: git clone https://github.com/ultralytics/yolov5")
            print(f"   - Run: python export.py --weights {model_file} --include onnx")
            print("   - Use the generated .onnx file instead")
            print("3. Train a new model using the Ultralytics package")
            print("=" * 60)
            
            return None
            
        except Exception as e:
            print(f"Error in YOLOv5 model handling: {e}")
            return None

    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image for YOLO inference"""
        if not isinstance(image, np.ndarray):
            raise TypeError("Input image must be a numpy array")
        
        return image
    
    def _infer(self, preprocessed_input: np.ndarray) -> Any:
        """Run YOLO inference"""
        if self.model is None:
            return None
        
        # Validate device again before inference as additional safety
        inference_device = self.device
        if inference_device in ['cuda', '0', 'gpu'] or (isinstance(inference_device, str) and inference_device.isdigit()):
            try:
                import torch
                if not torch.cuda.is_available():
                    print(f"WARNING: CUDA device '{inference_device}' not available during inference. Using CPU.")
                    inference_device = 'cpu'
            except ImportError:
                print(f"WARNING: PyTorch not available during inference. Using CPU instead of '{inference_device}'.")
                inference_device = 'cpu'
        
        # Use the device parameter in inference for Intel OpenVINO
        if self.use_openvino or inference_device.startswith('intel:'):
            results = self.model(preprocessed_input, device=inference_device.lower(), verbose=False)
        else:
            results = self.model(preprocessed_input, device=inference_device, verbose=False)
        
        return results
    
    def _postprocess(self, raw_output: Any) -> Dict[str, Any]:
        """Postprocess YOLO results"""
        return raw_output
        
    def draw(self, image: np.ndarray, results: Any) -> np.ndarray:
        annotated_frame = results[0].plot()
        return annotated_frame

    def _detect_model_task(self, model_file: str) -> str:
        """Auto-detect the YOLO model task from filename or model type"""
        model_file_lower = model_file.lower()
        
        # Check for task indicators in filename
        if 'seg' in model_file_lower or 'segment' in model_file_lower:
            return 'segment'
        elif 'cls' in model_file_lower or 'classify' in model_file_lower:
            return 'classify'
        elif 'pose' in model_file_lower:
            return 'pose'
        elif 'obb' in model_file_lower:
            return 'obb'
        else:
            # Default to detection
            return 'detect'
    
    # def get_device_info(self) -> Dict[str, Any]:
    #     """Get information about the current device configuration"""
    #     intel_hw = self._detect_intel_hardware()
    #     return {
    #         'device': self.device,
    #         'task': self.task,
    #         'use_openvino': self.use_openvino,
    #         'openvino_model_path': self.openvino_model_path,
    #         'intel_hardware': intel_hw,
    #         'model_loaded': self.is_loaded
    #     }

    def _check_model_compatibility(self, model_path: str) -> tuple[bool, str]:
        """
        Check if a model is compatible with Ultralytics before loading.
        Returns (is_compatible, reason)
        """
        try:
            # Check file extension
            if not model_path.lower().endswith(('.pt', '.onnx', '.torchscript', '.pb', '.tflite', '.engine')):
                return False, "Unsupported file format"
            
            # Check if it's a YOLOv5 model
            if model_path.lower().endswith('.pt') and self._is_yolov5_model(model_path):
                return False, "YOLOv5 model detected - may have compatibility issues"
            
            # Check if file exists and is readable
            if not os.path.exists(model_path):
                return False, "Model file does not exist"
            
            if not os.access(model_path, os.R_OK):
                return False, "Model file is not readable"
            
            # File seems compatible
            return True, "Model appears compatible"
            
        except Exception as e:
            return False, f"Error checking compatibility: {e}"

    def check_valid_model(self, model_path: str) -> bool:
        """Check if the model file is valid"""
        # Accept both local files and model names that Ultralytics can download
        if os.path.exists(model_path):
            if model_path.endswith(".pt") or ("yolov8" in model_path or "yolo11" in model_path or "yolo" in model_path):
                return True
        
        # Allow Ultralytics model names (they will be downloaded automatically)
        valid_model_names = [
            # YOLOv8 models
            'yolov8n.pt', 'yolov8s.pt', 'yolov8m.pt', 'yolov8l.pt', 'yolov8x.pt',
            'yolov8n-seg.pt', 'yolov8s-seg.pt', 'yolov8m-seg.pt', 'yolov8l-seg.pt', 'yolov8x-seg.pt',
            'yolov8n-pose.pt', 'yolov8s-pose.pt', 'yolov8m-pose.pt', 'yolov8l-pose.pt', 'yolov8x-pose.pt', 'yolov8x-pose-p6.pt',
            'yolov8n-obb.pt', 'yolov8s-obb.pt', 'yolov8m-obb.pt', 'yolov8l-obb.pt', 'yolov8x-obb.pt',
            'yolov8n-cls.pt', 'yolov8s-cls.pt', 'yolov8m-cls.pt', 'yolov8l-cls.pt', 'yolov8x-cls.pt',
            # YOLO11 models
            'yolo11n.pt', 'yolo11s.pt', 'yolo11m.pt', 'yolo11l.pt', 'yolo11x.pt',
            'yolo11n-seg.pt', 'yolo11s-seg.pt', 'yolo11m-seg.pt', 'yolo11l-seg.pt', 'yolo11x-seg.pt',
            'yolo11n-pose.pt', 'yolo11s-pose.pt', 'yolo11m-pose.pt', 'yolo11l-pose.pt', 'yolo11x-pose.pt',
            'yolo11n-obb.pt', 'yolo11s-obb.pt', 'yolo11m-obb.pt', 'yolo11l-obb.pt', 'yolo11x-obb.pt',
            'yolo11n-cls.pt', 'yolo11s-cls.pt', 'yolo11m-cls.pt', 'yolo11l-cls.pt', 'yolo11x-cls.pt'
        ]
        
        if model_path in valid_model_names:
            return True
            
        # Check if it's a directory (for OpenVINO models)
        if os.path.isdir(model_path) and model_path.endswith('_openvino_model'):
            return True

        return False

    def result_to_json(self, results: Any, output_format: str = "dict") -> Any:
        """Convert the ultralytics prediction to a comprehensive json format
        Supports all YOLO model types: detect, segment, pose, obb, classify
        Optionally include the original image as base64 encoded string for later post processing by the pipeline"""

        json_results = []
        
        # Handle Ultralytics Results objects properly
        for result in results:
            # Detection results (standard bounding boxes)
            if hasattr(result, 'boxes') and result.boxes is not None:
                boxes = result.boxes
                for i in range(len(boxes)):
                    # Get bounding box coordinates
                    if hasattr(boxes, 'xyxy'):
                        # Standard detection (xyxy format)
                        bbox = boxes.xyxy[i].cpu().numpy().tolist()
                        bbox_format = "xyxy"  # [x1, y1, x2, y2]
                    elif hasattr(boxes, 'xywh'):
                        # Center coordinates format
                        bbox = boxes.xywh[i].cpu().numpy().tolist()
                        bbox_format = "xywh"  # [x_center, y_center, width, height]
                    else:
                        bbox = []
                        bbox_format = "unknown"
                    
                    # Get confidence score
                    confidence = float(boxes.conf[i].cpu().numpy())
                    
                    # Get class ID and name
                    class_id = int(boxes.cls[i].cpu().numpy())
                    class_name = result.names[class_id] if hasattr(result, 'names') and result.names else str(class_id)
                    
                    detection_result = {
                        "type": "detection",
                        "class_id": class_id,
                        "class_name": class_name,
                        "confidence": confidence,
                        "bbox": bbox,
                        "bbox_format": bbox_format
                    }
                    
                    # Add OBB-specific data if available
                    if hasattr(result, 'obb') and result.obb is not None:
                        obb = result.obb
                        if i < len(obb.xyxyxyxy):
                            # Oriented bounding box coordinates (8 points: 4 corners with x,y each)
                            obb_coords = obb.xyxyxyxy[i].cpu().numpy().tolist()
                            detection_result.update({
                                "type": "obb",
                                "obb_coords": obb_coords,  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                            })
                    
                    json_results.append(detection_result)
            
            # Oriented Bounding Box (OBB) results - separate from regular detection
            if hasattr(result, 'obb') and result.obb is not None and not (hasattr(result, 'boxes') and result.boxes is not None):
                # This handles pure OBB models (not detection + OBB)
                obb = result.obb
                for i in range(len(obb.xyxyxyxy)):
                    # Get oriented bounding box coordinates (8 points: 4 corners with x,y each)
                    obb_coords = obb.xyxyxyxy[i].cpu().numpy().reshape(-1, 2).tolist()  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                    
                    # Get confidence score
                    confidence = float(obb.conf[i].cpu().numpy())
                    
                    # Get class ID and name
                    class_id = int(obb.cls[i].cpu().numpy())
                    class_name = result.names[class_id] if hasattr(result, 'names') and result.names else str(class_id)
                    
                    # Get regular bounding box if available (for compatibility)
                    bbox = []
                    if hasattr(obb, 'xyxy') and obb.xyxy is not None:
                        bbox = obb.xyxy[i].cpu().numpy().tolist()
                    
                    obb_result = {
                        "type": "obb",
                        "class_id": class_id,
                        "class_name": class_name,
                        "confidence": confidence,
                        "bbox": bbox,
                        "bbox_format": "xyxy",
                        "obb_coords": obb_coords,  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                        "obb_format": "xyxyxyxy"
                    }
                    
                    json_results.append(obb_result)
            
            # Segmentation results
            if hasattr(result, 'masks') and result.masks is not None:
                masks = result.masks
                boxes = result.boxes
                
                for i in range(len(masks.data)):
                    # Get mask data
                    mask = masks.data[i].cpu().numpy()
                    
                    # Convert mask to polygon or RLE encoding
                    mask_polygons = []
                    if hasattr(masks, 'xy') and masks.xy is not None and i < len(masks.xy):
                        # Polygon format (preferred)
                        polygon = masks.xy[i].tolist() if masks.xy[i] is not None else []
                        mask_polygons = [polygon] if polygon else []
                    
                    # Get corresponding box info if available
                    bbox = []
                    confidence = 0.0
                    class_id = 0
                    class_name = "unknown"
                    
                    if boxes is not None and i < len(boxes):
                        bbox = boxes.xyxy[i].cpu().numpy().tolist()
                        confidence = float(boxes.conf[i].cpu().numpy())
                        class_id = int(boxes.cls[i].cpu().numpy())
                        class_name = result.names[class_id] if hasattr(result, 'names') and result.names else str(class_id)
                    
                    segmentation_result = {
                        "type": "segmentation",
                        "class_id": class_id,
                        "class_name": class_name,
                        "confidence": confidence,
                        "bbox": bbox,
                        "bbox_format": "xyxy",
                        "mask_polygons": mask_polygons,
                        "mask_shape": mask.shape
                    }
                    
                    json_results.append(segmentation_result)
            
            # Pose detection results
            if hasattr(result, 'keypoints') and result.keypoints is not None:
                keypoints = result.keypoints
                boxes = result.boxes
                
                for i in range(len(keypoints.data)):
                    # Get keypoint data
                    kpts = keypoints.data[i].cpu().numpy()  # Shape: (num_keypoints, 3) - x, y, confidence
                    
                    # Convert to list of keypoints with names if available
                    keypoint_list = []
                    for j, kpt in enumerate(kpts):
                        keypoint_data = {
                            "id": j,
                            "x": float(kpt[0]),
                            "y": float(kpt[1]),
                            "confidence": float(kpt[2]) if len(kpt) > 2 else 1.0,
                            "visible": float(kpt[2]) > 0.5 if len(kpt) > 2 else True
                        }
                        
                        # Add keypoint names for COCO pose format
                        if hasattr(keypoints, 'names') and keypoints.names:
                            keypoint_data["name"] = keypoints.names.get(j, f"keypoint_{j}")
                        else:
                            # Default COCO keypoint names
                            coco_keypoints = [
                                "nose", "left_eye", "right_eye", "left_ear", "right_ear",
                                "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
                                "left_wrist", "right_wrist", "left_hip", "right_hip",
                                "left_knee", "right_knee", "left_ankle", "right_ankle"
                            ]
                            keypoint_data["name"] = coco_keypoints[j] if j < len(coco_keypoints) else f"keypoint_{j}"
                        
                        keypoint_list.append(keypoint_data)
                    
                    # Get corresponding box info if available
                    bbox = []
                    confidence = 0.0
                    class_id = 0
                    class_name = "person"  # Pose is typically for person detection
                    
                    if boxes is not None and i < len(boxes):
                        bbox = boxes.xyxy[i].cpu().numpy().tolist()
                        confidence = float(boxes.conf[i].cpu().numpy())
                        class_id = int(boxes.cls[i].cpu().numpy())
                        class_name = result.names[class_id] if hasattr(result, 'names') and result.names else "person"
                    
                    pose_result = {
                        "type": "pose",
                        "class_id": class_id,
                        "class_name": class_name,
                        "confidence": confidence,
                        "bbox": bbox,
                        "bbox_format": "xyxy",
                        "keypoints": keypoint_list,
                        "num_keypoints": len(keypoint_list)
                    }
                    
                    json_results.append(pose_result)
            
            # Classification results
            if hasattr(result, 'probs') and result.probs is not None:
                probs = result.probs
                
                # Get top predictions
                top_indices = probs.top5  # Top 5 predictions
                top_confidences = probs.top5conf.cpu().numpy()
                
                for idx, (class_idx, conf) in enumerate(zip(top_indices, top_confidences)):
                    class_id = int(class_idx)
                    confidence = float(conf)
                    class_name = result.names[class_id] if hasattr(result, 'names') and result.names else str(class_id)
                    
                    classification_result = {
                        "type": "classification",
                        "class_id": class_id,
                        "class_name": class_name,
                        "confidence": confidence,
                        "rank": idx + 1  # 1-based ranking
                    }
                    
                    json_results.append(classification_result)

        # Determine the overall result type based on what we found
        result_types = list(set([r.get("type", "unknown") for r in json_results]))
        primary_type = result_types[0] if len(result_types) == 1 else self.task

        # TODO: fix inconsistency with image and original_image between ultralytics and geti engines
        final_results = {
            "task_type": primary_type,
            "num_detections": len(json_results),
            "predictions": json_results
        }
        
        if output_format == "dict":
            return final_results
        
        return json.dumps(final_results)


if __name__ == "__main__":
    import logging
    import os
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Test Intel hardware detection and device optimization
    print("Testing UltralyticsEngine with Intel optimization...")
    
    # Test with different device configurations
    test_configs = [
        {'device': 'CPU'},
        {'device': 'GPU'}, 
        {'device': 'GPU.0'},
        {'device': 'GPU.1'},
        {'device': 'intel:cpu'},
        {'device': 'intel:gpu'},
        {'device': 'intel:gpu.0'},
        {'device': 'CPU', 'task': 'segment'},
        {'device': 'intel:cpu', 'task': 'detect'},
    ]
    
    for config in test_configs:
        print(f"\n--- Testing with device: {config['device']} ---")
        engine = UltralyticsEngine(**config)
        
        # device_info = engine.get_device_info()
        # print(f"Device info: {device_info}")
        
        test_model_path = "yolo11n.pt"
        loaded = engine.load(test_model_path)
        
        if loaded:
            logger.info(f"Model loaded successfully with device: {engine.device}")
            logger.info(f"Using OpenVINO: {engine.use_openvino}")
        else:
            logger.error("Failed to load model.")
        
        print("-" * 50)
