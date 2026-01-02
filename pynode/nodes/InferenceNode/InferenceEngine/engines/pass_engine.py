import numpy as np
from typing import Any, Dict, Optional
from .base_engine import BaseInferenceEngine


class PassEngine(BaseInferenceEngine):
    """Pass-through inference engine for data capture without inference"""
    
    display_name = "Passthrough"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Pass engine doesn't need a model
        self.model_path = None
        
    def _load_model(self, model_file: Optional[str], device: str) -> bool:
        """Pass engine doesn't need to load any model"""
        self.is_loaded = True
        self.logger.info("Pass engine loaded - no model required")
        return True
    
    def load(self, model_file: Optional[str] = None, device: Optional[str] = None) -> bool:
        """Override load to not require a model file"""
        if device is None:
            device = self.device or "CPU"
        else:
            device = device.upper()
            
        self.device = device
        self.model_path = None  # Pass engine doesn't use models
        
        return self._load_model(None, device)
    
    def check_valid_model(self, model_file: str) -> bool:
        """Pass engine doesn't require models - always returns True"""
        return True
    
    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        """No preprocessing needed - just return the image as-is"""
        return image
    
    def _infer(self, preprocessed_input: np.ndarray) -> Dict[str, Any]:
        """Create a placeholder prediction result"""
        height, width = preprocessed_input.shape[:2]
        
        # Return a simple placeholder result
        return {
            "success": True,
            "predictions": [],
            "image_width": width,
            "image_height": height,
            "processing_time": 0.001,  # Minimal processing time
            "model_name": "pass_engine",
            "confidence_threshold": 0.0
        }
    
    def _postprocess(self, raw_output: Dict[str, Any]) -> Dict[str, Any]:
        """Return the raw output with success flag"""
        raw_output["success"] = True
        raw_output["device"] = self.device
        return raw_output
    
    def draw(self, image: np.ndarray, results: Dict[str, Any]) -> np.ndarray:
        """Return the original image unchanged"""
        return image.copy()
    
    def result_to_json(self, results: Dict[str, Any], output_format: str = "dict") -> Any:
        """Convert results to JSON format"""
        json_result = {
            "success": results.get("success", True),
            "predictions": results.get("predictions", []),
            "image_width": results.get("image_width", 0),
            "image_height": results.get("image_height", 0),
            "processing_time": results.get("processing_time", 0.001),
            "model_name": "pass_engine",
            "engine_type": "PassEngine",
            "device": self.device,
            "confidence_threshold": 0.0,
            "total_detections": 0
        }
        
        if output_format == "dict":
            return json_result
        else:
            import json
            return json.dumps(json_result, indent=2)