"""
Confidence Filter Node - filters messages based on detection confidence.
Passes through messages that contain detections meeting the confidence threshold.
"""

from typing import Any, Dict, List
from base_node import BaseNode


class ConfidenceFilterNode(BaseNode):
    """
    Confidence Filter node - filters messages based on detection confidence score.
    Output 0: Detections with confidence >= threshold
    Output 1: Detections with confidence < threshold
    """
    display_name = 'Confidence Filter'
    icon = '📊'
    category = 'function'
    color = '#C7E9C0'
    border_color = '#74C476'
    text_color = '#000000'
    input_count = 1
    output_count = 2  # Output 0: >= threshold, Output 1: < threshold
    
    properties = [
        {
            'name': 'threshold',
            'label': 'Confidence Threshold',
            'type': 'number',
            'default': 0.5,
            'min': 0,
            'max': 1,
            'step': 0.01,
            'help': 'Minimum confidence score (0-1) to pass to output 0'
        },
        {
            'name': 'threshold_source',
            'label': 'Threshold Source',
            'type': 'select',
            'options': [
                {'value': 'config', 'label': 'Use configured value'},
                {'value': 'msg', 'label': 'Use msg.threshold'}
            ],
            'default': 'config',
            'help': 'Where to read the threshold value from'
        },
        {
            'name': 'detection_path',
            'label': 'Detection Path',
            'type': 'text',
            'default': 'payload.detection',
            'help': 'Path to detection object in message (e.g., "payload.detection")'
        },
        {
            'name': 'confidence_field',
            'label': 'Confidence Field',
            'type': 'text',
            'default': 'confidence',
            'help': 'Name of the confidence field in detection object'
        }
    ]
    
    def __init__(self, node_id=None, name="confidence filter"):
        super().__init__(node_id, name)
        self.configure({
            'threshold': 0.5,
            'threshold_source': 'config',
            'detection_path': 'payload.detection',
            'confidence_field': 'confidence'
        })
    
    def _get_nested_value(self, obj: Dict, path: str) -> Any:
        """Get a nested value from a dictionary using dot notation."""
        parts = path.split('.')
        current = obj
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Filter messages based on detection confidence.
        Output 0: Detections with confidence >= threshold
        Output 1: Detections with confidence < threshold
        """
        # Get threshold from msg or config based on setting
        threshold_source = self.config.get('threshold_source', 'config')
        if threshold_source == 'msg' and 'threshold' in msg:
            try:
                threshold = float(msg['threshold'])
            except (TypeError, ValueError):
                threshold = float(self.config.get('threshold', 0.5))
        else:
            threshold = float(self.config.get('threshold', 0.5))
        
        detection_path = self.config.get('detection_path', 'payload.detection')
        confidence_field = self.config.get('confidence_field', 'confidence')
        
        # Get detection from message
        detection = self._get_nested_value(msg, detection_path)
        
        if detection is None:
            # No detection found, send to low confidence output
            self.send(msg, 1)
            return
        
        # Get confidence value
        confidence = None
        if isinstance(detection, dict):
            confidence = detection.get(confidence_field)
        
        if confidence is None:
            # No confidence field found, send to low confidence output
            self.send(msg, 1)
            return
        
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            # Invalid confidence value, send to low confidence output
            self.send(msg, 1)
            return
        
        # Route based on threshold
        if confidence >= threshold:
            self.send(msg, 0)  # High confidence
        else:
            self.send(msg, 1)  # Low confidence
