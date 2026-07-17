#!/usr/bin/env python3
"""
Utilities for summarising and converting inference engine result formats.
"""

from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


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
    """Create a Rectangle."""
    return Rectangle(x=x, y=y, width=width, height=height, type=ShapeType.RECTANGLE)


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
    'create_rectangle',
    'extract_detections_summary',
]
