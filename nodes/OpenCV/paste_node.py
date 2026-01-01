"""
OpenCV Paste Node - pastes an image onto another at a specific position.
Used for compositing operations like replacing regions in an image.
"""

import cv2
import numpy as np
from typing import Any, Dict, Optional, Tuple
from nodes.base_node import BaseNode, Info


# Build info content
_info = Info()
_info.add_text("Pastes a foreground image onto a background image at a specified position. Useful for compositing operations like replacing regions in an image.")

_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0 (top):", "Background image - the original full image to paste onto"),
    ("Input 1 (bottom):", "Foreground image - the region to paste (e.g., a processed crop)")
)

_info.add_header("Output")
_info.add_text("The combined image with the foreground pasted onto the background.")

_info.add_header("Position Source")
_info.add_bullets(
    ("From msg.bbox:", "Automatically uses bounding box coordinates from upstream nodes like CropNode"),
    ("Manual:", "Specify X and Y coordinates in the properties")
)

_info.add_header("Typical Usage")
_info.add_text("Connect the original image to Input 0, and the processed crop (e.g., blurred face) to Input 1. The node will paste the crop back to its original position.")

_info.add_header("Example Flow")
_info.add_code("Camera → Crop → Blur → Paste").text("(with Camera also connected to Paste Input 0)").end()


class PasteNode(BaseNode):
    """
    Paste node - pastes a foreground image onto a background image at specified coordinates.
    Useful for replacing regions (e.g., blurred faces back into original image).
    
    Input 0: Background image (the original full image)
    Input 1: Foreground image (the region to paste, e.g., blurred crop)
    
    The position can come from:
    - msg.bbox on the foreground message (from CropNode)
    - Manual coordinates in properties
    """
    display_name = 'Paste'
    icon = '📋'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 2  # Input 0: background, Input 1: foreground
    output_count = 1
    
    info = str(_info)
    
    DEFAULT_CONFIG = {
        'position_source': 'bbox',
        'x': 0,
        'y': 0,
        'resize_to_fit': 'true'
    }
    
    properties = [
        {
            'name': 'position_source',
            'label': 'Position Source',
            'type': 'select',
            'options': [
                {'value': 'bbox', 'label': 'From msg.bbox (auto from CropNode)'},
                {'value': 'manual', 'label': 'Manual coordinates'}
            ],
            'default': DEFAULT_CONFIG['position_source'],
            'help': 'Where to get the paste position from'
        },
        {
            'name': 'x',
            'label': 'X Position',
            'type': 'number',
            'default': DEFAULT_CONFIG['x'],
            'help': 'X coordinate for manual positioning'
        },
        {
            'name': 'y',
            'label': 'Y Position',
            'type': 'number',
            'default': DEFAULT_CONFIG['y'],
            'help': 'Y coordinate for manual positioning'
        },
        {
            'name': 'resize_to_fit',
            'label': 'Resize to Fit',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes (resize foreground to bbox size)'},
                {'value': 'false', 'label': 'No (use foreground as-is)'}
            ],
            'default': DEFAULT_CONFIG['resize_to_fit'],
            'help': 'Resize foreground to match the original bbox size'
        }
    ]
    
    def __init__(self, node_id=None, name="paste"):
        super().__init__(node_id, name)
        self._background: Optional[np.ndarray] = None
        self._background_msg: Optional[Dict] = None
        self._format_type: Optional[str] = None
    
    def on_start(self):
        """Reset state on start."""
        super().on_start()
        self._background = None
        self._background_msg = None
        self._format_type = None
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Process images:
        - Input 0: Store as background
        - Input 1: Paste onto background and send
        """
        if 'payload' not in msg:
            return
        
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            return
        
        if input_index == 0:
            # Background image - store it
            self._background = img.copy()
            self._background_msg = msg.copy()
            self._format_type = format_type
        else:
            # Foreground image - paste onto background
            if self._background is None:
                self.report_error("No background image received yet")
                return
            
            self._paste_foreground(img, msg)
    
    def _paste_foreground(self, foreground: np.ndarray, fg_msg: Dict[str, Any]):
        """Paste foreground onto background at specified position."""
        position_source = self.config.get('position_source', 'bbox')
        resize_to_fit = self.get_config_bool('resize_to_fit', True)
        
        # Get position - check multiple places for bbox
        bbox = None
        if position_source == 'bbox':
            # Try msg.bbox first (dict format)
            if 'bbox' in fg_msg and isinstance(fg_msg['bbox'], dict):
                bbox = fg_msg['bbox']
            # Try msg.payload.bbox (list format from CropNode)
            elif isinstance(fg_msg.get('payload'), dict) and 'bbox' in fg_msg['payload']:
                bbox_list = fg_msg['payload']['bbox']
                if isinstance(bbox_list, list) and len(bbox_list) >= 4:
                    bbox = {'x1': bbox_list[0], 'y1': bbox_list[1], 'x2': bbox_list[2], 'y2': bbox_list[3]}
        
        if bbox:
            x1 = int(bbox.get('x1', 0))
            y1 = int(bbox.get('y1', 0))
            x2 = int(bbox.get('x2', x1 + foreground.shape[1]))
            y2 = int(bbox.get('y2', y1 + foreground.shape[0]))
        else:
            x1 = self.get_config_int('x', 0)
            y1 = self.get_config_int('y', 0)
            x2 = x1 + foreground.shape[1]
            y2 = y1 + foreground.shape[0]
        
        # Create output image from background (already checked not None in caller)
        assert self._background is not None
        result = self._background.copy()
        bg_h, bg_w = result.shape[:2]
        
        # Clamp coordinates to image bounds
        x1 = max(0, min(x1, bg_w - 1))
        y1 = max(0, min(y1, bg_h - 1))
        x2 = max(x1 + 1, min(x2, bg_w))
        y2 = max(y1 + 1, min(y2, bg_h))
        
        target_w = x2 - x1
        target_h = y2 - y1
        
        # Resize foreground if needed
        if resize_to_fit:
            fg_resized = cv2.resize(foreground, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        else:
            fg_resized = foreground
            # Adjust target region to match foreground size
            fg_h, fg_w = foreground.shape[:2]
            x2 = min(x1 + fg_w, bg_w)
            y2 = min(y1 + fg_h, bg_h)
            # Crop foreground if it extends beyond background
            fg_resized = foreground[:y2-y1, :x2-x1]
        
        # Handle channel mismatch
        if len(result.shape) == 3 and len(fg_resized.shape) == 2:
            fg_resized = cv2.cvtColor(fg_resized, cv2.COLOR_GRAY2BGR)
        elif len(result.shape) == 2 and len(fg_resized.shape) == 3:
            fg_resized = cv2.cvtColor(fg_resized, cv2.COLOR_BGR2GRAY)
        
        # Paste
        result[y1:y2, x1:x2] = fg_resized
        
        # Build output message
        out_msg = self._background_msg.copy() if self._background_msg else {}
        out_msg['payload']['image'] = self.encode_image(result, self._format_type or 'numpy_array')
        
        self.send(out_msg)
