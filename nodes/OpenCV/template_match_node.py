"""
OpenCV Template Matching Node - finds template in image.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class TemplateMatchNode(BaseNode):
    """
    Template Match node - finds occurrences of a template image in the input.
    """
    display_name = 'Template Match'
    icon = '🔍'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 2  # Input 0: image, Input 1: template
    output_count = 1
    
    DEFAULT_CONFIG = {
        'method': 'ccoeff_normed',
        'threshold': 0.8,
        'multi_match': 'no',
        'draw_matches': 'yes',
        'match_color': '0,255,0'
    }
    
    properties = [
        {
            'name': 'method',
            'label': 'Method',
            'type': 'select',
            'options': [
                {'value': 'ccoeff_normed', 'label': 'Correlation Coefficient (normalized)'},
                {'value': 'ccorr_normed', 'label': 'Cross Correlation (normalized)'},
                {'value': 'sqdiff_normed', 'label': 'Squared Difference (normalized)'},
                {'value': 'ccoeff', 'label': 'Correlation Coefficient'},
                {'value': 'ccorr', 'label': 'Cross Correlation'},
                {'value': 'sqdiff', 'label': 'Squared Difference'}
            ],
            'default': DEFAULT_CONFIG['method'],
            'help': 'Template matching method'
        },
        {
            'name': 'threshold',
            'label': 'Threshold',
            'type': 'number',
            'default': DEFAULT_CONFIG['threshold'],
            'min': 0,
            'max': 1,
            'step': 0.05,
            'help': 'Match threshold (0-1)'
        },
        {
            'name': 'multi_match',
            'label': 'Multi Match',
            'type': 'select',
            'options': [
                {'value': 'yes', 'label': 'Yes (find all)'},
                {'value': 'no', 'label': 'No (best only)'}
            ],
            'default': DEFAULT_CONFIG['multi_match'],
            'help': 'Find multiple matches above threshold'
        },
        {
            'name': 'draw_matches',
            'label': 'Draw Matches',
            'type': 'select',
            'options': [
                {'value': 'yes', 'label': 'Yes'},
                {'value': 'no', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['draw_matches'],
            'help': 'Draw rectangles around matches'
        },
        {
            'name': 'match_color',
            'label': 'Match Color (B,G,R)',
            'type': 'text',
            'default': DEFAULT_CONFIG['match_color'],
            'help': 'Color for match rectangles'
        }
    ]
    
    def __init__(self, node_id=None, name="template match"):
        super().__init__(node_id, name)
        self._template = None
    
    def _parse_color(self, color_str):
        """Parse color string to BGR tuple."""
        try:
            parts = [int(x.strip()) for x in str(color_str).split(',')]
            if len(parts) >= 3:
                return (parts[0], parts[1], parts[2])
            return (0, 255, 0)
        except:
            return (0, 255, 0)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Process template matching."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.send(msg)
            return
        
        # Input 1 is the template
        if input_index == 1:
            self._template = img
            return
        
        # Input 0 is the image to search
        if self._template is None:
            msg['matches'] = []
            msg['match_count'] = 0
            self.send(msg)
            return
        
        method_str = self.config.get('method', 'ccoeff_normed')
        threshold = self.get_config_float('threshold', 0.8)
        multi_match = self.get_config_bool('multi_match', False)
        draw = self.get_config_bool('draw_matches', True)
        match_color = self._parse_color(self.config.get('match_color', '0,255,0'))
        
        # Map method string to OpenCV constant
        method_map = {
            'ccoeff_normed': cv2.TM_CCOEFF_NORMED,
            'ccorr_normed': cv2.TM_CCORR_NORMED,
            'sqdiff_normed': cv2.TM_SQDIFF_NORMED,
            'ccoeff': cv2.TM_CCOEFF,
            'ccorr': cv2.TM_CCORR,
            'sqdiff': cv2.TM_SQDIFF
        }
        method = method_map.get(method_str, cv2.TM_CCOEFF_NORMED)
        
        # Perform template matching
        result = cv2.matchTemplate(img, self._template, method)
        
        h, w = self._template.shape[:2]
        matches = []
        
        # For SQDIFF methods, lower is better
        is_sqdiff = method in [cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED]
        
        if multi_match:
            if is_sqdiff:
                locations = np.where(result <= (1 - threshold))
            else:
                locations = np.where(result >= threshold)
            
            for pt in zip(*locations[::-1]):
                score = float(result[pt[1], pt[0]])
                matches.append({
                    'x': int(pt[0]),
                    'y': int(pt[1]),
                    'width': w,
                    'height': h,
                    'score': score if not is_sqdiff else 1 - score
                })
        else:
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            
            if is_sqdiff:
                best_loc = min_loc
                best_score = 1 - min_val
            else:
                best_loc = max_loc
                best_score = max_val
            
            if (is_sqdiff and min_val <= (1 - threshold)) or \
               (not is_sqdiff and max_val >= threshold):
                matches.append({
                    'x': int(best_loc[0]),
                    'y': int(best_loc[1]),
                    'width': w,
                    'height': h,
                    'score': float(best_score)
                })
        
        # Draw matches if requested
        if draw and matches:
            if len(img.shape) == 2:
                output = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            else:
                output = img.copy()
            
            for match in matches:
                pt1 = (match['x'], match['y'])
                pt2 = (match['x'] + w, match['y'] + h)
                cv2.rectangle(output, pt1, pt2, match_color, 2)
            
            if 'payload' not in msg or not isinstance(msg['payload'], dict):
                msg['payload'] = {}
            msg['payload']['image'] = self.encode_image(output, format_type)
        
        msg['matches'] = matches
        msg['match_count'] = len(matches)
        self.send(msg)
