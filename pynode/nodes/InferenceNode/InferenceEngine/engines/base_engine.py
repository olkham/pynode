from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import logging
import numpy as np


class BaseInferenceEngine(ABC):
    """Base class for all inference engines"""
    
    # Class attribute that should be overridden by subclasses
    display_name = "Base Inference Engine"
    
    def __init__(self, **kwargs):
        
        self.model_path = kwargs.get('model_path', None)
        self.device = kwargs.get('device', "CPU")  # Default device

        self.is_loaded = False
        self.type = self.__class__.__name__
        self.logger = logging.getLogger(self.__class__.__name__)
        
    
    def load(self, model_file: Optional[str] = None, device: Optional[str] = None) -> bool:
        """
        Load the model for inference
        
        Args:
            model_file: Path to the model file. If None, uses self.model_path from constructor
            device: Device to load the model on. If None, uses self.device from constructor
            
        Returns:
            bool: True if model loaded successfully, False otherwise
        """
        # Use constructor values if parameters are None
        if model_file is None:
            model_file = self.model_path
        
        if device is None:
            device = self.device
            
        # Validate that we have required values
        if model_file is None:
            raise ValueError("model_file must be provided either as parameter or in constructor")
            
        if device is None:
            device = "CPU"  # Default fallback
        else:
            device = device.upper()
            
        # Store the values
        self.model_path = model_file
        self.device = device
        
        # Delegate to subclass implementation
        return self._load_model(model_file, device)
    
    @abstractmethod
    def _load_model(self, model_file: str, device: str) -> bool:
        """Load the model - must be implemented by subclasses"""
        pass
    
    def infer(self, image: np.ndarray) -> Dict[str, Any]:
        """
        Runs inference on the input image
        
        Args:
            image: Input image data
            
        Returns:
            Dict containing inference results
        """
        if not self.is_loaded:
            return {
                "success": False,
                "error": "Model not loaded",
                "device": self.device
            }
            
        try:
            # Preprocessing
            preprocessed_input = self._preprocess(image)
            
            # Inference
            raw_output = self._infer(preprocessed_input)
            
            # Postprocessing
            processed_output = self._postprocess(raw_output)

            return processed_output
        except Exception as e:
            self.logger.error(f"Inference failed: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "device": self.device
            }
        #     }
            
        # except Exception as e:
        #     self.logger.error(f"Inference failed: {str(e)}")
        #     return {
        #         "success": False,
        #         "error": str(e),
        #         "device": self.device
        #     }
    
    
    @abstractmethod
    def check_valid_model(self, model_file: str) -> bool:
        """Check if the model file is valid"""
        pass
    
    @abstractmethod
    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        """Preprocess input data (expects a numpy array) - must be implemented by subclasses"""
        pass
    
    @abstractmethod
    def _infer(self, preprocessed_input: np.ndarray) -> np.ndarray:
        """Run inference - must be implemented by subclasses"""
        pass
    
    @abstractmethod
    def _postprocess(self, raw_output: Any) -> Any:
        """Postprocess model output - must be implemented by subclasses"""
        pass
    
    @classmethod
    def get_display_name(cls) -> str:
        """Get the user-friendly display name for this engine"""
        return cls.display_name
    
    def get_info(self) -> Dict[str, Any]:
        """Get information about the current engine state"""
        return {
            "engine_type": self.__class__.__name__,
            "display_name": self.__class__.display_name,
            "device": self.device,
            "is_loaded": self.is_loaded,
            "model_path": self.model_path
        }

    def __str__(self):
        info = self.get_info()
        return f"Engine Type: {info['engine_type']}, Device: {info['device']}, Loaded: {info['is_loaded']}, Model Path: {info['model_path']}"
    
    @abstractmethod
    def draw(self, image: np.ndarray, results: Any) -> np.ndarray:
        """Draw the results on the image - must be implemented by subclasses"""
        pass
    
    @abstractmethod
    def result_to_json(self, results: Any, output_format: str = "dict") -> Any:
        """Convert inference results to JSON format - must be implemented by subclasses"""
        pass