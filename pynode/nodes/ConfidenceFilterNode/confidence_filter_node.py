"""
Confidence Filter Node - filters messages based on detection confidence.
Passes through messages that contain detections meeting the confidence threshold.
"""

import copy
from typing import Any, Dict, List
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Splits detection arrays based on confidence scores, sending high-confidence detections to output 0 and low-confidence to output 1.")
_info.add_header("Input")
_info.add_bullets(
    (f"{MessageKeys.PAYLOAD}.detections:", "Array of detection objects, each containing a confidence score."),
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Message with detections having confidence >= threshold."),
    ("Output 1:", "Message with detections having confidence < threshold."),
)
_info.add_header("Properties")
_info.add_bullets(
    ("Threshold:", "Minimum confidence score (0-1) to separate detections."),
    ("Threshold Source:", "Use configured value or read from msg.threshold."),
    ("Detections Path:", "Path to the detections array in the message."),
    ("Confidence Field:", "Name of the confidence field within each detection."),
)


class ConfidenceFilterNode(BaseNode):
    """
    Confidence Filter node - splits detection arrays based on confidence scores.
    Always outputs to both ports:
    Output 0: Detections with confidence >= threshold
    Output 1: Detections with confidence < threshold
    """
    info = str(_info)
    display_name = 'Confidence Filter'
    icon = '📊'
    category = 'vision'
    color = '#C7E9C0'
    border_color = '#74C476'
    text_color = '#000000'
    input_count = 1
    output_count = 2  # Output 0: >= threshold, Output 1: < threshold
    
    DEFAULT_CONFIG = {
        'threshold_source': 'manual',  # or 'msg'
        'threshold': 0.5,
        'detections_path': f'{MessageKeys.PAYLOAD}.{MessageKeys.CV.DETECTIONS}',
        'confidence_field': MessageKeys.CV.CONFIDENCE
    }
    
    properties = [
        {
            'name': 'threshold_source',
            'label': 'Threshold Source',
            'type': 'select',
            'options': [
                {'value': 'manual', 'label': 'Use manual value'},
                {'value': 'msg', 'label': 'Use msg.threshold'}
            ],
            'default': DEFAULT_CONFIG['threshold_source'],
            'help': 'Where to read the threshold value from'
        },
        {
            'name': 'threshold',
            'label': 'Confidence Threshold',
            'type': 'number',
            'default': DEFAULT_CONFIG['threshold'],
            'min': 0,
            'max': 1,
            'step': 0.01,
            'help': 'Minimum confidence score (0-1) to pass to output 0',
            'showIf': {'threshold_source': 'manual'}
        },
        {
            'name': 'detections_path',
            'label': 'Detections Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['detections_path'],
            'help': f'Path to detections array in message (e.g., "{MessageKeys.PAYLOAD}.{MessageKeys.CV.DETECTIONS}")'
        },
        {
            'name': 'confidence_field',
            'label': 'Confidence Field',
            'type': 'text',
            'default': DEFAULT_CONFIG['confidence_field'],
            'help': 'Name of the confidence field in each detection object'
        }
    ]
    
    def __init__(self, node_id=None, name="confidence filter"):
        super().__init__(node_id, name)
    
    def _set_nested_value(self, obj: Dict, path: str, value: Any):
        """Set a nested value in a dictionary using dot notation."""
        parts = path.split('.')
        current = obj
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Split detections based on confidence threshold.
        Always outputs to both ports:
        Output 0: Detections with confidence >= threshold
        Output 1: Detections with confidence < threshold
        """
        # Get threshold from msg or config based on setting
        threshold_source = self.config.get('threshold_source', 'config')
        if threshold_source == 'msg' and 'threshold' in msg:
            try:
                threshold = float(msg['threshold'])
            except (TypeError, ValueError):
                threshold = self.get_config_float('threshold', 0.5)
        else:
            threshold = self.get_config_float('threshold', 0.5)
        
        detections_path = self.config.get('detections_path', f'{MessageKeys.PAYLOAD}.{MessageKeys.CV.DETECTIONS}')
        confidence_field = self.config.get('confidence_field', MessageKeys.CV.CONFIDENCE)
        
        # Get detections array from message
        detections = self._get_nested_value(msg, detections_path)
        
        if not isinstance(detections, list):
            # No detections array found, send empty arrays to both outputs
            high_msg = copy.deepcopy(msg)
            low_msg = copy.deepcopy(msg)
            
            # Set empty detection arrays
            self._set_nested_value(high_msg, detections_path, [])
            self._set_nested_value(low_msg, detections_path, [])
            
            high_msg['threshold'] = threshold
            low_msg['threshold'] = threshold
            
            self.send(high_msg, 0)
            self.send(low_msg, 1)
            return
        
        # Split detections based on confidence
        high_confidence_detections = []
        low_confidence_detections = []
        
        for detection in detections:
            if not isinstance(detection, dict):
                # Invalid detection, add to low confidence
                low_confidence_detections.append(detection)
                continue
            
            confidence = detection.get(confidence_field)
            if confidence is None:
                # No confidence field, add to low confidence
                low_confidence_detections.append(detection)
                continue
            
            try:
                confidence = float(confidence)
                if confidence >= threshold:
                    high_confidence_detections.append(detection)
                else:
                    low_confidence_detections.append(detection)
            except (TypeError, ValueError):
                # Invalid confidence value, add to low confidence
                low_confidence_detections.append(detection)
        
        # Create output messages
        high_msg = copy.deepcopy(msg)
        low_msg = copy.deepcopy(msg)
        
        # Set filtered detection arrays
        self._set_nested_value(high_msg, detections_path, high_confidence_detections)
        self._set_nested_value(low_msg, detections_path, low_confidence_detections)
        
        # Add threshold and detection counts to messages
        high_msg['threshold'] = threshold
        low_msg['threshold'] = threshold
        
        # Update detection counts if they exist
        if MessageKeys.CV.DETECTION_COUNT in msg:
            high_msg[MessageKeys.CV.DETECTION_COUNT] = len(high_confidence_detections)
            low_msg[MessageKeys.CV.DETECTION_COUNT] = len(low_confidence_detections)
        
        # Always send to both outputs
        self.send(high_msg, 0)  # High confidence detections
        self.send(low_msg, 1)   # Low confidence detections
