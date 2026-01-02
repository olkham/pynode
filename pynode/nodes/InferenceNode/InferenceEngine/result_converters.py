#!/usr/bin/env python3
"""
Utilities for converting between different inference engine result formats.
Uses official Geti SDK data models for proper format compliance.
Supports conversion between Ultralytics and Geti inference result formats.
"""

from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Import Geti SDK data models
try:
    from geti_sdk.data_models.shapes import Rectangle as GetiRectangle, ShapeType as GetiShapeType
    from geti_sdk.data_models.predictions import Prediction
    from geti_sdk.data_models.label import ScoredLabel
    from geti_sdk.data_models.annotations import Annotation
    from geti_sdk.data_models.annotation_scene import AnnotationScene

    GETI_SDK_AVAILABLE = True
    
except ImportError as e:
    logger.warning(f"Geti SDK not available: {e}. Using fallback Rectangle class.")
    GETI_SDK_AVAILABLE = False
    GetiRectangle = None
    GetiShapeType = None


# Fallback classes that work whether SDK is available or not
class ShapeType:
    RECTANGLE = "RECTANGLE"


class Rectangle:
    def __init__(self, x: float, y: float, width: float, height: float, type=ShapeType.RECTANGLE):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.type = type
    
    def __repr__(self):
        return f"Rectangle(x={self.x}, y={self.y}, width={self.width}, height={self.height}, type=<ShapeType.{self.type}: '{self.type}'>)"


def create_rectangle(x: float, y: float, width: float, height: float):
    """Create a Rectangle using Geti SDK if available, otherwise use fallback."""
    if GETI_SDK_AVAILABLE and GetiRectangle is not None and GetiShapeType is not None:
        return GetiRectangle(x=int(x), y=int(y), width=int(width), height=int(height))
    else:
        return Rectangle(x=x, y=y, width=width, height=height, type=ShapeType.RECTANGLE)


# def ultralytics_to_geti(ultralytics_result: Dict[str, Any]) -> Prediction:
#     """
#     Convert Ultralytics inference result format to Geti Prediction object using official SDK data models.
    
#     Args:
#         ultralytics_result: Result from Ultralytics engine in format:
#             {
#                 'results': {
#                     'engine': 'ultralytics',
#                     'model_type': 'yolo', 
#                     'results': [
#                         {
#                             'detections': [
#                                 {
#                                     'bbox': [x1, y1, x2, y2],
#                                     'confidence': float,
#                                     'class_id': int,
#                                     'class_name': str
#                                 }
#                             ],
#                             'image_shape': (height, width)
#                         }
#                     ]
#                 }
#             }
    
#     Returns:
#         Geti SDK Prediction object with proper annotations
#     """
#     if not GETI_SDK_AVAILABLE:
#         logger.error("Geti SDK not available. Cannot create Prediction object.")
#         raise ImportError("Geti SDK is required to create Prediction objects")

#     ultra_detections = ultralytics_result.get('results', [])
#     annotations = []
    
#     # Iterate through each result item in the results array
#     for result_item in ultra_detections:
#         # Each result_item should be a dict with 'detections' and 'image_shape'
#         if isinstance(result_item, dict):
#             detections = result_item.get('detections', [])
            
#             # Iterate through each detection in this result item
#             for detection in detections:
#                 bbox = detection.get('bbox', [])
#                 if len(bbox) >= 4:
#                     # Convert from [x1, y1, x2, y2] to Rectangle(x, y, width, height)
#                     x1, y1, x2, y2 = bbox[:4]
#                     x = float(x1)
#                     y = float(y1)
#                     width = float(x2 - x1)
#                     height = float(y2 - y1)
                    
#                     # Create Rectangle using helper function
#                     shape = create_rectangle(x=x, y=y, width=width, height=height)
                    
#                     # Create ScoredLabel using Geti SDK
#                     scored_label = ScoredLabel(
#                         name=detection.get('class_name', f"class_{detection.get('class_id', 0)}"),
#                         probability=float(detection.get('confidence', 0.0))
#                     )
                    
#                     # Create Annotation object with shape and labels
#                     annotation = Annotation(
#                         shape=shape,
#                         labels=[scored_label]
#                     )
#                     annotations.append(annotation)
    
#     # Create and return a Prediction object
#     prediction = Prediction(annotations=annotations)
#     return prediction


# def ultralytics_to_geti_dict(ultralytics_result: Dict[str, Any]) -> Dict[str, Any]:
#     """
#     Convert Ultralytics inference result format to Geti format dictionary.
#     This is a wrapper that returns dictionary format for backward compatibility.
    
#     Args:
#         ultralytics_result: Result from Ultralytics engine
    
#     Returns:
#         Dict in Geti format for backward compatibility
#     """
#     # Get the Prediction object
#     prediction = ultralytics_to_geti(ultralytics_result)
    
#     # Convert back to dictionary format for compatibility
#     geti_predictions = []
#     for annotation in prediction.annotations:
#         shape = annotation.shape
#         labels = annotation.labels
        
#         if labels and len(labels) > 0:
#             scored_label = labels[0]  # Take the first label
#             geti_prediction = {
#                 'label': scored_label.name,
#                 'confidence': scored_label.probability,
#                 'shape': shape,
#                 'scored_label': scored_label
#             }
#             geti_predictions.append(geti_prediction)
    
#     geti_result = {
#         'success': True,
#         'results': {
#             'engine': 'geti',
#             'model_type': 'intel_geti',
#             'results': {
#                 'predictions': geti_predictions
#             }
#         },
#         'model_id': ultralytics_result.get('model_id'),
#         'device': ultralytics_result.get('device')
#     }
    
#     return geti_result


# def geti_to_ultralytics(geti_result: Dict[str, Any], image_shape: Optional[tuple] = None) -> Dict[str, Any]:
#     """
#     Convert Geti inference result format to Ultralytics format.
    
#     Args:
#         geti_result: Result from Geti engine using official SDK data models
#         image_shape: Optional tuple (height, width) for the original image
    
#     Returns:
#         Dict in Ultralytics format
#     """
#     if not geti_result.get('success', False):
#         return geti_result
    
#     geti_results = geti_result.get('results', {})
#     predictions = geti_results.get('results', {}).get('predictions', [])
    
#     ultralytics_detections = []
    
#     # Create a simple class name to ID mapping
#     class_names = []
#     for pred in predictions:
#         label = pred.get('label', 'unknown')
#         if label not in class_names:
#             class_names.append(label)
    
#     class_name_to_id = {name: idx for idx, name in enumerate(sorted(class_names))}
    
#     for prediction in predictions:
#         shape = prediction.get('shape')
#         if shape and hasattr(shape, 'x') and hasattr(shape, 'y'):
#             # Convert from Rectangle(x, y, width, height) to [x1, y1, x2, y2]
#             x1 = float(shape.x)
#             y1 = float(shape.y)
#             x2 = float(shape.x + shape.width)
#             y2 = float(shape.y + shape.height)
            
#             label = prediction.get('label', 'unknown')
#             detection = {
#                 'bbox': [x1, y1, x2, y2],
#                 'confidence': float(prediction.get('confidence', 0.0)),
#                 'class_id': class_name_to_id.get(label, 0),
#                 'class_name': label
#             }
#             ultralytics_detections.append(detection)
    
#     # Default image shape if not provided
#     if image_shape is None:
#         image_shape = (1080, 1920)  # Default HD resolution
    
#     ultralytics_result = {
#         'success': True,
#         'results': {
#             'engine': 'ultralytics',
#             'model_type': 'yolo',
#             'results': [
#                 {
#                     'detections': ultralytics_detections,
#                     'image_shape': image_shape
#                 }
#             ]
#         },
#         'model_id': geti_result.get('model_id'),
#         'device': geti_result.get('device')
#     }
    
#     return ultralytics_result


# def create_geti_prediction(label: str, confidence: float, bbox: List[float]) -> Dict[str, Any]:
#     """
#     Create a proper Geti prediction using SDK data models.
    
#     Args:
#         label: Class label name
#         confidence: Confidence score (0.0 to 1.0)
#         bbox: Bounding box as [x1, y1, x2, y2]
    
#     Returns:
#         Dict representing a Geti prediction with proper SDK Rectangle and ScoredLabel
#     """
#     if len(bbox) < 4:
#         raise ValueError("bbox must contain at least 4 values [x1, y1, x2, y2]")
    
#     x1, y1, x2, y2 = bbox[:4]
#     x = float(x1)
#     y = float(y1)
#     width = float(x2 - x1)
#     height = float(y2 - y1)
    
#     shape = create_rectangle(x=x, y=y, width=width, height=height)
    
#     if GETI_SDK_AVAILABLE:
#         # Create ScoredLabel using Geti SDK
#         scored_label = ScoredLabel(
#             name=str(label),
#             probability=float(confidence)
#         )
        
#         return {
#             'label': str(label),
#             'confidence': float(confidence),
#             'shape': shape,
#             'scored_label': scored_label  # Include SDK object
#         }
#     else:
#         return {
#             'label': str(label),
#             'confidence': float(confidence),
#             'shape': shape
#         }


# def create_geti_annotation(predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
#     """
#     Create a Geti-compatible annotation structure from predictions using SDK data models.
    
#     Args:
#         predictions: List of prediction dictionaries with label, confidence, and shape
    
#     Returns:
#         Dict representing a complete Geti annotation structure with SDK objects when available
#     """
#     if not GETI_SDK_AVAILABLE:
#         logger.warning("Geti SDK not available. Creating simplified annotation structure.")
#         return {
#             'predictions': predictions
#         }
    
#     # If SDK is available, create proper Annotation objects
#     annotations = []
#     for pred in predictions:
#         shape = pred.get('shape')
#         scored_label = pred.get('scored_label')
        
#         if shape and scored_label:
#             try:
#                 # Create Annotation using the SDK
#                 annotation = Annotation(
#                     labels=[scored_label],
#                     shape=shape
#                 )
#                 annotations.append(annotation)
#             except Exception as e:
#                 logger.warning(f"Failed to create Annotation object: {e}. Using fallback.")
#                 annotations.append(pred)
#         else:
#             # Fallback to original prediction if missing SDK objects
#             annotations.append(pred)
    
#     return {
#         'predictions': predictions,  # Keep original format for compatibility
#         'annotations': annotations   # Include SDK objects when available
#     }


# def normalize_result_format(result: Dict[str, Any], target_format: str = 'ultralytics', image_shape: Optional[tuple] = None) -> Dict[str, Any]:
#     """
#     Normalize inference results to a target format.
    
#     Args:
#         result: Inference result from any supported engine
#         target_format: Target format ('ultralytics' or 'geti')
#         image_shape: Optional image shape for conversions that need it
    
#     Returns:
#         Dict in the target format
#     """
#     if not isinstance(result, dict):
#         raise ValueError("Result must be a dictionary")
    
#     current_engine = result.get('results', {}).get('engine', 'unknown')
    
#     if target_format == 'ultralytics':
#         if current_engine == 'geti':
#             return geti_to_ultralytics(result, image_shape)
#         elif current_engine == 'ultralytics':
#             return result  # Already in target format
#         else:
#             logger.warning(f"Unknown source engine: {current_engine}")
#             return result
    
#     elif target_format == 'geti':
#         if current_engine == 'ultralytics':
#             return ultralytics_to_geti_dict(result)
#         elif current_engine == 'geti':
#             return result  # Already in target format
#         else:
#             logger.warning(f"Unknown source engine: {current_engine}")
#             return result
    
#     else:
#         raise ValueError(f"Unsupported target format: {target_format}")



def extract_detections_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract a simplified summary of detections from any result format.
    
    Args:
        result: Inference result from any supported engine
    
    Returns:
        Dict with simplified detection summary
    """
    if not result.get('success', False):
        return {
            'engine': 'unknown', 
            'detection_count': 0, 
            'classes_detected': [], 
            'confidence_range': (0.0, 0.0), 
            'detections': []
        }
    
    engine = result.get('results', {}).get('engine', 'unknown')
    detections = []
    
    if engine == 'ultralytics':
        ultra_results = result.get('results', {}).get('results', [])
        for result_item in ultra_results:
            for detection in result_item.get('detections', []):
                detections.append({
                    'class_name': detection.get('class_name', 'unknown'),
                    'confidence': detection.get('confidence', 0.0),
                    'bbox': detection.get('bbox', [])
                })
    
    elif engine == 'geti':
        predictions = result.get('results', {}).get('results', {}).get('predictions', [])
        for prediction in predictions:
            shape = prediction.get('shape')
            bbox = []
            if shape and hasattr(shape, 'x'):
                bbox = [shape.x, shape.y, shape.x + shape.width, shape.y + shape.height]
            
            detections.append({
                'class_name': prediction.get('label', 'unknown'),
                'confidence': prediction.get('confidence', 0.0),
                'bbox': bbox
            })
    
    classes_detected = list(set(d['class_name'] for d in detections))
    confidences = [d['confidence'] for d in detections]
    confidence_range = (min(confidences, default=0.0), max(confidences, default=0.0))
    
    return {
        'engine': engine,
        'detection_count': len(detections),
        'classes_detected': classes_detected,
        'confidence_range': confidence_range,
        'detections': detections
    }


# Export all functions
__all__ = [
    'Rectangle',
    'ShapeType', 
    # 'ultralytics_to_geti',
    # 'ultralytics_to_geti_dict',
    'geti_to_ultralytics', 
    'create_geti_prediction',
    'create_geti_annotation',
    'create_rectangle',
    # 'normalize_result_format',
    'extract_detections_summary',
    'GETI_SDK_AVAILABLE'
]
