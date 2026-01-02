import sys
import os
import tempfile
import zipfile
from flask import json


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
import numpy as np
from typing import Any, Dict
import shutil

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

# Try to import geti_sdk dependencies - fail gracefully if not available
try:
    from geti_sdk.deployment import Deployment
    from geti_sdk.utils import show_image_with_annotation_scene
    from geti_sdk.data_models.predictions import Prediction
    GETI_SDK_AVAILABLE = True
except ImportError:
    # If geti_sdk is not installed, create placeholder to allow module to load
    # The engine will raise a clear error when actually instantiated
    GETI_SDK_AVAILABLE = False
    Deployment = None
    show_image_with_annotation_scene = None
    Prediction = None

class GetiEngine(BaseInferenceEngine):
    """Inference engine for Geti models"""
    
    # Define the user-friendly display name
    display_name = "Geti"
    
    def __init__(self, **kwargs):
        # Check if geti_sdk is available before doing anything else
        if not GETI_SDK_AVAILABLE:
            raise ImportError(
                "geti_sdk is not installed. GetiEngine requires the geti-sdk package. "
                "Install it with: pip install geti-sdk"
            )
        
        super().__init__(**kwargs)
        self.model_path = kwargs.get('model_path', None)
        self.device = kwargs.get('device', "CPU")  # Default device
        self.output_format = kwargs.get('output_format', "geti")  # Default output format
        self.deployment = None

    
    def _load_with_geti_sdk(self, model_path: str) -> bool:
        """Try to load with actual Geti SDK"""
        try:
            
            # Extract deployment to temporary directory
            if model_path.endswith(".zip"):
                temp_dir = tempfile.mkdtemp()
                with zipfile.ZipFile(model_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)

                model_path = temp_dir

            # Load deployment
            self.deployment = Deployment.from_folder(model_path)
            self.deployment.load_inference_models(device=self.device)
            self.model_path = model_path
            
            self.logger.info("Geti SDK deployment loaded successfully")
            return True
            
        except ImportError:
            self.logger.warning("Geti SDK not installed. Install with: pip install geti-sdk")
            return False
        except Exception as e:
            self.logger.error(f"Error loading with Geti SDK: {e}")
            return False

    def _load_model(self, model_file: str, device: str = "CPU") -> bool:

        if device is None:
            device = self.device.upper()
        else:
            # Update the instance device with the passed parameter
            self.device = device.upper()

        if model_file is None:
            model_file = self.model_path

        if not self.check_valid_model(model_file):
            return False

        # If it's a deployment package
        if not self._load_with_geti_sdk(model_file):
            raise RuntimeError("Failed to load Geti deployment package")

        # self.model_path = model_file
        self.is_loaded = True
        return True


    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image for Geti inference"""
        if not isinstance(image, np.ndarray):
            raise TypeError("Input image must be a numpy array")
        return image
    
    def _infer(self, preprocessed_input: np.ndarray) -> Any:
        """Run Geti inference"""
        if self.deployment is not None:
            # Use actual Geti SDK
            try:
                prediction = self.deployment.infer(image=preprocessed_input)
                return prediction
            except Exception as e:
                self.logger.error(f"Geti inference error: {e}")
                return None
        else:
            return None
        
    def _postprocess(self, raw_output: Any) -> Any:
        """Postprocess Geti results"""
        return raw_output
    
    def cleanup(self):
        """Clean up temporary files"""
        if self.model_path and os.path.exists(self.model_path):
            try:
                shutil.rmtree(self.model_path)
                self.logger.info("Cleaned up temporary model files")
            except Exception as e:
                self.logger.warning(f"Failed to cleanup model files: {e}")

    def check_valid_model(self, model_file: str) -> bool:
        # Check if the model file is valid
        if not os.path.exists(model_file):
            self.logger.warning(f"Model file not found: {model_file}")
            return False
        
        # If it's a directory, check for Geti deployment structure
        if os.path.isdir(model_file):
            required_items = ['deployment', 'example_code', 'LICENSE', 'README.md', 'sample_image.jpg']
            missing_items = []
            
            for item in required_items:
                item_path = os.path.join(model_file, item)
                if not os.path.exists(item_path):
                    missing_items.append(item)
            
            if missing_items:
                self.logger.warning(f"Directory missing required Geti deployment items: {missing_items}")
                return False
            
            # Additional check: ensure 'deployment' is actually a directory
            deployment_dir = os.path.join(model_file, 'deployment')
            if not os.path.isdir(deployment_dir):
                self.logger.warning("'deployment' should be a directory")
                return False
            
            return True

        # Check if the model file has a .zip extension - TODO add more checks that it's a deployment package from Geti
        if model_file.endswith(".zip"):
            return True

        return False

    def draw(self, image: np.ndarray, results: Any) -> np.ndarray:
        image = show_image_with_annotation_scene(image, results, show_results=False, channel_order='bgr')
        return image

    def result_to_json(self, results: Any, output_format: str = "dict") -> Any:
        #convert the results to a simple json format
        
        # Convert Prediction object to dictionary
        predictions_dict = None
        if results is not None:
            try:
                # Try to use the model_dump method if available (Pydantic models)
                if hasattr(results, 'model_dump'):
                    predictions_dict = results.model_dump()
                elif hasattr(results, 'dict'):
                    predictions_dict = results.dict()
                elif hasattr(results, 'to_dict'):
                    predictions_dict = results.to_dict()
                elif hasattr(results, '__dict__'):
                    predictions_dict = results.__dict__
                else:
                    predictions_dict = str(results)
                
                # Always run through our serialization converter to handle numpy types
                if isinstance(predictions_dict, dict):
                    predictions_dict = self._convert_to_serializable(predictions_dict)
                    
            except Exception as e:
                self.logger.warning(f"Failed to convert prediction to dict: {e}")
                predictions_dict = str(results)
        
        json_results = {
            "predictions": predictions_dict,
            "original_image": None
        }
        

        if output_format == "dict":
            return json_results
        
        return json.dumps(json_results)
    
    def _convert_to_serializable(self, obj):
        """Recursively convert objects to JSON serializable format"""
        if isinstance(obj, dict):
            return {key: self._convert_to_serializable(value) for key, value in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._convert_to_serializable(item) for item in obj]
        elif isinstance(obj, np.ndarray):
            return obj.tolist()  # Convert numpy arrays to lists
        elif isinstance(obj, (np.integer, np.floating)):
            # Convert numpy scalars to Python scalars
            if isinstance(obj, np.floating):
                # For coordinates, convert to int; for probabilities, keep as float
                if hasattr(obj, 'item'):
                    value = obj.item()
                else:
                    value = float(obj)
                # If it's a whole number, convert to int (for coordinates)
                if isinstance(value, float) and value.is_integer():
                    return int(value)
                else:
                    return float(value)  # Ensure it's a Python float, not numpy float
            else:
                return obj.item() if hasattr(obj, 'item') else int(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)  # Convert numpy booleans to Python booleans
        elif hasattr(obj, 'model_dump'):
            return self._convert_to_serializable(obj.model_dump())
        elif hasattr(obj, 'dict'):
            return self._convert_to_serializable(obj.dict())
        elif hasattr(obj, '__dict__'):
            return self._convert_to_serializable(obj.__dict__)
        elif isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        else:
            return str(obj)

if __name__ == "__main__":
    # Example usage - updated to work with base engine interface
    import logging
    logging.basicConfig(level=logging.INFO)
    
    engine = GetiEngine()
    
    # Try to load from deployment using the load_from_deployment method
    deployment_path = "C:/Users/olive/OneDrive/Projects/InferNode/InferenceEngine/models/geti_sdk-deployment-yolox"
    if os.path.exists(deployment_path):
        if engine.load(deployment_path):
            print("✓ Geti deployment loaded successfully")
            
            # Test with a test image
            test_image_path = "C:/Users/olive/OneDrive/Projects/InferNode/InferenceEngine/test_image/test.jpg"
            if os.path.exists(test_image_path):
                test_image = cv2.imread(test_image_path)
                if test_image is not None:
                    print(f"✓ Test image loaded: {test_image.shape}")
                    results = engine.infer(test_image)
                    output = engine.draw(test_image, results)
                    json_results = engine.result_to_json(results)
                    cv2.imshow("Inference Output", output)
                    print("✓ Inference results (JSON):")
                    print(json_results)
                    
                    print("✓ Inference results:")
                    print(results)
                    cv2.waitKey(0)
                    cv2.destroyAllWindows()
                    
                else:
                    print("✗ Failed to load test image")
            else:
                print(f"✗ Test image not found at {test_image_path}")
                print("Creating dummy test image for demonstration...")
                # Create a dummy image for testing
                dummy_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
                results = engine.infer(dummy_image)
                print("✓ Inference results with dummy image:")
                print(results)
        else:
            print("✗ Failed to load Geti deployment")
    else:
        print(f"✗ Deployment file not found at {deployment_path}")