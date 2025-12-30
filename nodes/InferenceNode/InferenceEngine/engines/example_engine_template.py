#!/usr/bin/env python3
"""
Example template for creating a new inference engine.
This file demonstrates how to implement the BaseInferenceEngine interface.
"""

import numpy as np
from typing import Any, Optional
import json

# Import the base engine class
try:
    from .base_engine import BaseInferenceEngine
except ImportError:
    from base_engine import BaseInferenceEngine


class ExampleEngine(BaseInferenceEngine):
    """
    Example inference engine template.
    
    This class demonstrates how to create a new inference engine by:
    1. Inheriting from BaseInferenceEngine
    2. Setting the display_name class attribute
    3. Implementing all required abstract methods
    """
    
    # REQUIRED: Define the user-friendly display name for your engine
    display_name = "My Custom AI Engine"
    
    def __init__(self, **kwargs):
        """
        Initialize your engine.
        
        You can add custom parameters here while calling super().__init__(**kwargs)
        to handle standard parameters like model_path and device.
        """
        super().__init__(**kwargs)
        
        # Add any custom initialization here
        self.custom_parameter = kwargs.get('custom_parameter', 'default_value')
        self.model = None
    
    def _load_model(self, model_file: str, device: str) -> bool:
        """
        Load your model from the specified file.
        
        Args:
            model_file: Path to the model file
            device: Target device (e.g., 'cpu', 'gpu', 'intel:gpu')
            
        Returns:
            bool: True if model loaded successfully, False otherwise
        """
        try:
            # Implement your model loading logic here
            # For example:
            # self.model = your_framework.load_model(model_file)
            # self.model.to(device)
            
            self.logger.info(f"Loading model from {model_file} on device {device}")
            
            # For this example, we'll just simulate loading
            self.model = {"loaded": True, "path": model_file, "device": device}
            self.is_loaded = True
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load model: {e}")
            return False
    
    def check_valid_model(self, model_file: str) -> bool:
        """
        Check if the model file is valid for this engine.
        
        Args:
            model_file: Path to the model file
            
        Returns:
            bool: True if the model is valid, False otherwise
        """
        # Implement your model validation logic here
        # For example, check file extension, file format, etc.
        
        # Example: Check if file exists and has correct extension
        import os
        if not os.path.exists(model_file):
            return False
            
        # Check for your specific model format
        if model_file.endswith(('.pt', '.onnx', '.pb', '.h5')):
            return True
            
        return False
    
    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        """
        Preprocess the input image for inference.
        
        Args:
            image: Input image as numpy array
            
        Returns:
            np.ndarray: Preprocessed image
        """
        # Implement your preprocessing logic here
        # For example: resize, normalize, convert color space, etc.
        
        # Example preprocessing
        if not isinstance(image, np.ndarray):
            raise TypeError("Input image must be a numpy array")
        
        # Example: Ensure image is in the right format
        if len(image.shape) == 3 and image.shape[2] == 3:
            # Convert BGR to RGB if needed
            # preprocessed = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            preprocessed = image  # For this example, no conversion
        else:
            preprocessed = image
            
        return preprocessed
    
    def _infer(self, preprocessed_input: np.ndarray) -> Any:
        """
        Run inference on the preprocessed input.
        
        Args:
            preprocessed_input: Preprocessed image data
            
        Returns:
            Any: Raw inference results from your model
        """
        if self.model is None:
            return None
            
        # Implement your inference logic here
        # For example:
        # results = self.model.predict(preprocessed_input)
        
        # For this example, return simulated results
        results = {
            "detections": [
                {
                    "class_id": 0,
                    "class_name": "example_object",
                    "confidence": 0.85,
                    "bbox": [100, 100, 200, 200]
                }
            ]
        }
        
        return results
    
    def _postprocess(self, raw_output: Any) -> Any:
        """
        Postprocess the raw inference results.
        
        Args:
            raw_output: Raw results from _infer method
            
        Returns:
            Any: Processed results ready for output
        """
        # Implement your postprocessing logic here
        # For example: apply NMS, filter by confidence, format results, etc.
        
        # For this example, just return the raw output
        return raw_output
    
    def draw(self, image: np.ndarray, results: Any) -> np.ndarray:
        """
        Draw inference results on the image.
        
        Args:
            image: Original input image
            results: Processed inference results
            
        Returns:
            np.ndarray: Image with drawn annotations
        """
        # Implement your visualization logic here
        # For example: draw bounding boxes, labels, confidence scores, etc.
        
        # For this example, just return the original image
        # In a real implementation, you would draw the results
        annotated_image = image.copy()
        
        # Example drawing logic:
        # if results and "detections" in results:
        #     for detection in results["detections"]:
        #         bbox = detection["bbox"]
        #         cv2.rectangle(annotated_image, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
        #         cv2.putText(annotated_image, f"{detection['class_name']}: {detection['confidence']:.2f}", 
        #                    (bbox[0], bbox[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        return annotated_image

    def result_to_json(self, results: Any, output_format: str = "dict") -> str:
        """
        Convert inference results to JSON format.
        
        Args:
            results: Processed inference results
            original_image: Optional original image for base64 encoding
            
        Returns:
            str: JSON string representation of results
        """
        # Implement your JSON conversion logic here
        
        # Example JSON formatting
        json_results = {
            "engine_type": self.__class__.__name__,
            "display_name": self.display_name,
            "results": results,
            "original_image": None
        }
        
        # Optionally include base64 encoded image
        # if original_image is not None:
        #     import cv2
        #     import base64
        #     success, buffer = cv2.imencode('.jpg', original_image)
        #     if success:
        #         json_results["original_image"] = base64.b64encode(buffer.tobytes()).decode('utf-8')

        if output_format == "dict":
            return json.dumps(json_results, default=str)
        elif output_format == "json":
            return json.dumps(json_results, default=str)
        else:
            raise ValueError(f"Unsupported output format: {output_format}")


# Example usage and testing
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Create engine instance
    engine = ExampleEngine(custom_parameter="test_value")
    
    # Test display name
    print(f"Engine display name: {engine.get_display_name()}")
    print(f"Engine info: {engine.get_info()}")
    
    # Test model loading (with a dummy model file)
    dummy_model_path = "example_model.pt"
    
    # Note: This will fail because the file doesn't exist, but shows the workflow
    if engine.check_valid_model(dummy_model_path):
        if engine.load(dummy_model_path):
            print("Model loaded successfully!")
            
            # Test inference with dummy image
            dummy_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
            results = engine.infer(dummy_image)
            print(f"Inference results: {results}")
            
            # Test visualization
            annotated = engine.draw(dummy_image, results)
            print(f"Annotated image shape: {annotated.shape}")
            
            # Test JSON conversion
            json_output = engine.result_to_json(results)
            print(f"JSON output: {json_output}")
        else:
            print("Failed to load model")
    else:
        print(f"Invalid model file: {dummy_model_path}")
        print("This is expected since the file doesn't exist.")
