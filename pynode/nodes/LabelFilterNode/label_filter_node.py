"""
Label Filter Node - filters messages based on detection labels.
Passes through messages that contain detections matching allowed labels.
"""

from typing import Any, Dict, List
from pynode.nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Filters messages based on object detection class labels. Routes messages to different outputs based on whether they contain matching detections.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with detection data (e.g., from inference node).")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Messages with detections matching allowed labels."),
    ("Output 1:", "Messages without matching labels.")
)
_info.add_header("Match Modes")
_info.add_bullets(
    ("Any:", "Pass if any detection matches any allowed label."),
    ("All:", "Pass only if all allowed labels are present in detections.")
)
_info.add_header("Options")
_info.add_bullets(
    ("Labels:", "Comma-separated list of allowed labels (e.g., 'person, car, dog')."),
    ("Case Sensitive:", "Whether label matching is case-sensitive."),
    ("Filter Detections:", "Remove non-matching detections from output message.")
)


class LabelFilterNode(BaseNode):
    """
    Label Filter node - filters messages based on detection class labels.
    Only passes through messages containing detections that match the allowed labels.
    """
    display_name = 'Label Filter'
    icon = '🏷️'
    category = 'vision'
    color = '#C7E9C0'
    border_color = '#74C476'
    text_color = '#000000'
    input_count = 1
    output_count = 2  # Output 1: matched, Output 2: unmatched
    info = str(_info)

    DEFAULT_CONFIG = {
        'labels': 'person, car',
        'match_mode': 'any',
        'case_sensitive': False,
        'filter_detections': True,
        'detections_path': 'payload.detections'
    }

    properties = [
        {
            'name': 'labels',
            'label': 'Allowed Labels',
            'type': 'text',
            'default': DEFAULT_CONFIG['labels'],
            'help': 'Comma-separated list of labels to allow (e.g., "person, car, dog")'
        },
        {
            'name': 'match_mode',
            'label': 'Match Mode',
            'type': 'select',
            'options': [
                {'value': 'any', 'label': 'Any label matches'},
                {'value': 'all', 'label': 'All labels must be present'}
            ],
            'default': DEFAULT_CONFIG['match_mode'],
            'help': 'How to match multiple labels'
        },
        {
            'name': 'case_sensitive',
            'label': 'Case Sensitive',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['case_sensitive'],
        },
        {
            'name': 'filter_detections',
            'label': 'Filter Detections Array',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['filter_detections'],
            'help': 'Remove non-matching detections from the output'
        },
        {
            'name': 'detections_path',
            'label': 'Detections Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['detections_path'],
            'help': f'Path to detection(s) in message (e.g., "{DEFAULT_CONFIG["detections_path"]}")'
        }
    ]
    
    def __init__(self, node_id=None, name="label filter"):
        super().__init__(node_id, name)

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
    
    def _set_nested_value(self, obj: Dict, path: str, value: Any):
        """Set a nested value in a dictionary using dot notation."""
        parts = path.split('.')
        current = obj
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
    
    def _parse_labels(self) -> List[str]:
        """Parse the comma-separated labels config into a list."""
        labels_str = self.config.get('labels', '')
        case_sensitive = self.config.get('case_sensitive', False)
        
        labels = [l.strip() for l in labels_str.split(',') if l.strip()]
        
        if not case_sensitive:
            labels = [l.lower() for l in labels]
        
        return labels
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Filter messages based on detection labels.
        Output 0: Messages with matching labels
        Output 1: Messages without matching labels
        """
        allowed_labels = self._parse_labels()
        if not allowed_labels:
            # No labels configured, pass everything through output 0
            self.send(msg, 0)
            return
        
        detections_path = self.config.get('detections_path', self.DEFAULT_CONFIG['detections_path'])
        detection_data = self._get_nested_value(msg, detections_path)
        
        if detection_data is None:
            # No detection found, send to unmatched output
            self.send(msg, 1)
            return
        
        # Handle both single detection (dict) and array of detections (list)
        if isinstance(detection_data, dict):
            detections = [detection_data]
            is_single = True
        elif isinstance(detection_data, list):
            detections = detection_data
            is_single = False
        else:
            # Invalid detection data, send to unmatched output
            self.send(msg, 1)
            return
        
        case_sensitive = self.config.get('case_sensitive', self.DEFAULT_CONFIG['case_sensitive'])
        match_mode = self.config.get('match_mode', self.DEFAULT_CONFIG['match_mode'])
        filter_detections = self.config.get('filter_detections', self.DEFAULT_CONFIG['filter_detections'])

        # Get labels from detections
        detected_labels = set()
        matching_detections = []
        
        for detection in detections:
            label = detection.get('class_name', detection.get('label', detection.get('class', '')))
            if not case_sensitive:
                label = label.lower() if label else ''
            
            detected_labels.add(label)
            
            if label in allowed_labels:
                matching_detections.append(detection)
        
        # Check if we have a match based on mode
        has_match = False
        if match_mode == 'any':
            # At least one allowed label must be present
            has_match = bool(detected_labels & set(allowed_labels))
        else:  # 'all'
            # All allowed labels must be present
            has_match = set(allowed_labels).issubset(detected_labels)
        
        if has_match:
            # Modify msg directly - send() handles deep copying
            if filter_detections and matching_detections:
                # Replace detections with only matching ones
                if 'payload' in msg and isinstance(msg['payload'], dict):
                    # For single detection, keep as single; for array, keep as array
                    if is_single:
                        self._set_nested_value(msg, detections_path, matching_detections[0])
                    else:
                        self._set_nested_value(msg, detections_path, matching_detections)
                        # Update detection count if present
                        if 'detection_count' in msg['payload']:
                            msg['payload']['detection_count'] = len(matching_detections)
            
            self.send(msg, 0)
        else:
            # No match, send to second output (msg passes through with all properties preserved)
            self.send(msg, 1)
