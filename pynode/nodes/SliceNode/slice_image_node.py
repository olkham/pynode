"""
Slice Image Node - slices images into tiles for improved detection of small objects.
Based on SAHI (Slicing Aided Hyper Inference) methodology.
"""

import numpy as np
from typing import Any, Dict, List, Tuple, Optional
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    cv2 = None
    _HAS_CV2 = False

_info = Info()
_info.add_text("Divides images into overlapping tiles for improved detection of small objects. Based on SAHI (Slicing Aided Hyper Inference) methodology.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Image message with 'image' field"))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Array of image slices with offset metadata, or split messages per slice"),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Output Mode:", "Array (all slices in one message) or Split (separate messages)"),
    ("Auto Slice:", "Automatically calculate slice size based on image resolution"),
    ("Slice Width/Height:", "Manual slice dimensions in pixels"),
    ("Overlap Ratios:", "Overlap between adjacent slices (0-1)"),
    ("Include Full Image:", "Also include the original full image in output"),
)


class SliceImageNode(BaseNode):
    """
    Slice Image Node - divides images into overlapping tiles for better detection
    of small objects in large images.
    
    Implements SAHI-style slicing with configurable tile size and overlap.
    Outputs an array of image tiles with their offset information.
    """
    display_name = 'Slice Image'
    info = str(_info)
    icon = '🔲'
    category = 'vision'
    color = '#4ECDC4'
    border_color = '#26A69A'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'slice_width': 640,
        'slice_height': 640,
        'overlap_width_ratio': 0.2,
        'overlap_height_ratio': 0.2,
        'auto_slice': False,
        'include_full_image': True,
        'output_mode': 'array',
        'min_area_ratio': 0.1,
        'drop_messages': False
    }
    
    properties = [
        {
            'name': 'output_mode',
            'label': 'Output Mode',
            'type': 'select',
            'options': [
                {'value': 'array', 'label': 'Array (all slices in one message)'},
                {'value': 'split', 'label': 'Split (separate message per slice)'}
            ],
            'default': 'array'
        },
        {
            'name': 'auto_slice',
            'label': 'Auto Slice Resolution',
            'type': 'checkbox',
            'default': False
        },
        {
            'name': 'slice_width',
            'label': 'Slice Width (pixels)',
            'type': 'number',
            'default': 640,
            'showIf': {'auto_slice': False}
        },
        {
            'name': 'slice_height',
            'label': 'Slice Height (pixels)',
            'type': 'number',
            'default': 640,
            'showIf': {'auto_slice': False}
        },
        {
            'name': 'overlap_width_ratio',
            'label': 'Overlap Width Ratio (0-1)',
            'type': 'number',
            'default': 0.2,
            'showIf': {'auto_slice': False}
        },
        {
            'name': 'overlap_height_ratio',
            'label': 'Overlap Height Ratio (0-1)',
            'type': 'number',
            'default': 0.2,
            'showIf': {'auto_slice': False}
        },
        {
            'name': 'include_full_image',
            'label': 'Include Full Image in Output',
            'type': 'checkbox',
            'default': True
        },
        {
            'name': 'min_area_ratio',
            'label': 'Min Area Ratio (for auto slice)',
            'type': 'number',
            'default': 0.1,
            'showIf': {'auto_slice': True}
        }
    ]
    
    def __init__(self, node_id=None, name="slice_image"):
        super().__init__(node_id, name)
    
    def _get_auto_slice_params(self, height: int, width: int) -> Tuple[int, int, int, int]:
        """
        Calculate automatic slice parameters based on image resolution.
        Returns (x_overlap, y_overlap, slice_width, slice_height)
        """
        resolution = height * width
        factor = self._calc_resolution_factor(resolution)
        
        orientation = self._calc_aspect_ratio_orientation(width, height)
        
        if factor <= 18:  # Low resolution (e.g., 300x300, 640x640)
            return self._get_resolution_params("low", height, width, orientation)
        elif factor < 21:  # Medium resolution (e.g., 1024x1024)
            return self._get_resolution_params("medium", height, width, orientation)
        elif factor < 24:  # High resolution (e.g., 2048x2048)
            return self._get_resolution_params("high", height, width, orientation)
        else:  # Ultra-high resolution (e.g., 4096x4096+)
            return self._get_resolution_params("ultra-high", height, width, orientation)
    
    def _calc_resolution_factor(self, resolution: int) -> int:
        """Calculate power of 2 closest to image resolution."""
        expo = 0
        while 2 ** expo < resolution:
            expo += 1
        return expo - 1
    
    def _calc_aspect_ratio_orientation(self, width: int, height: int) -> str:
        """Determine image orientation based on aspect ratio."""
        if width < height:
            return "vertical"
        elif width > height:
            return "horizontal"
        return "square"
    
    def _calc_ratio_and_slice(self, orientation: str, slide: int = 1, ratio: float = 0.1) -> Tuple[int, int, float, float]:
        """Calculate slice rows/cols and overlap ratios based on orientation."""
        if orientation == "vertical":
            return slide, slide * 2, ratio, ratio
        elif orientation == "horizontal":
            return slide * 2, slide, ratio, ratio
        return slide, slide, ratio, ratio
    
    def _get_resolution_params(self, resolution: str, height: int, width: int, orientation: str) -> Tuple[int, int, int, int]:
        """Get slice parameters based on resolution category."""
        if resolution == "medium":
            split_row, split_col, overlap_h, overlap_w = self._calc_ratio_and_slice(orientation, 1, 0.8)
        elif resolution == "high":
            split_row, split_col, overlap_h, overlap_w = self._calc_ratio_and_slice(orientation, 2, 0.4)
        elif resolution == "ultra-high":
            split_row, split_col, overlap_h, overlap_w = self._calc_ratio_and_slice(orientation, 4, 0.4)
        else:  # low
            return 0, 0, width, height  # No slicing needed
        
        slice_height = height // split_col
        slice_width = width // split_row
        x_overlap = int(slice_width * overlap_w)
        y_overlap = int(slice_height * overlap_h)
        
        return x_overlap, y_overlap, slice_width, slice_height
    
    def _get_slice_bboxes(
        self,
        image_height: int,
        image_width: int,
        slice_height: int,
        slice_width: int,
        overlap_height_ratio: float,
        overlap_width_ratio: float
    ) -> List[List[int]]:
        """
        Generate bounding boxes for slicing an image.
        
        Returns list of [x_min, y_min, x_max, y_max] for each slice.
        """
        if overlap_height_ratio >= 1.0 or overlap_width_ratio >= 1.0:
            raise ValueError("Overlap ratio must be less than 1.0")
        
        y_overlap = int(overlap_height_ratio * slice_height)
        x_overlap = int(overlap_width_ratio * slice_width)
        
        slice_bboxes = []
        y_min = 0
        
        while y_min < image_height:
            y_max = y_min + slice_height
            x_min = 0
            
            while x_min < image_width:
                x_max = x_min + slice_width
                
                # Handle edge cases - ensure slices don't exceed image bounds
                if y_max > image_height or x_max > image_width:
                    xmax = min(image_width, x_max)
                    ymax = min(image_height, y_max)
                    xmin = max(0, xmax - slice_width)
                    ymin = max(0, ymax - slice_height)
                    slice_bboxes.append([xmin, ymin, xmax, ymax])
                else:
                    slice_bboxes.append([x_min, y_min, x_max, y_max])
                
                x_min = x_max - x_overlap
            
            y_min = y_max - y_overlap
        
        return slice_bboxes
    
    def _slice_image(self, image: np.ndarray) -> List[Dict[str, Any]]:
        """
        Slice the image into tiles based on configuration.
        
        Returns list of dicts with 'image', 'offset', and 'bbox' for each slice.
        """
        height, width = image.shape[:2]
        
        auto_slice = self.get_config_bool('auto_slice', False)
        
        if auto_slice:
            x_overlap, y_overlap, slice_width, slice_height = self._get_auto_slice_params(height, width)
            if slice_width >= width and slice_height >= height:
                # No slicing needed - image is small enough
                return [{
                    'image': image,
                    'offset': [0, 0],
                    'bbox': [0, 0, width, height],
                    'is_full_image': True
                }]
            overlap_width_ratio = x_overlap / slice_width if slice_width > 0 else 0.2
            overlap_height_ratio = y_overlap / slice_height if slice_height > 0 else 0.2
        else:
            slice_width = self.get_config_int('slice_width', 640)
            slice_height = self.get_config_int('slice_height', 640)
            overlap_width_ratio = self.get_config_float('overlap_width_ratio', 0.2)
            overlap_height_ratio = self.get_config_float('overlap_height_ratio', 0.2)
        
        # Get slice bounding boxes
        slice_bboxes = self._get_slice_bboxes(
            image_height=height,
            image_width=width,
            slice_height=slice_height,
            slice_width=slice_width,
            overlap_height_ratio=overlap_height_ratio,
            overlap_width_ratio=overlap_width_ratio
        )
        
        slices = []
        for bbox in slice_bboxes:
            x_min, y_min, x_max, y_max = bbox
            slice_img = image[y_min:y_max, x_min:x_max].copy()
            slices.append({
                'image': slice_img,
                'offset': [x_min, y_min],
                'bbox': bbox,
                'is_full_image': False
            })
        
        return slices
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Process incoming image and output slices."""
        if not _HAS_CV2:
            self.report_error("OpenCV (cv2) is required for image slicing")
            return
        
        payload = msg.get('payload')
        if payload is None:
            self.report_error("No payload in message")
            return
        
        # Decode the image
        image, input_format = self.decode_image(payload)
        if image is None or input_format is None:
            self.report_error("Failed to decode image from payload")
            return
        
        # Slice the image
        slices = self._slice_image(image)
        
        # Check if we should include the full image
        include_full = self.get_config_bool('include_full_image', True)
        output_mode = self.config.get('output_mode', 'array')
        
        # Get original message ID for tracking
        parent_msg_id = msg.get('_msgid', '')
        
        # Prepare output slices
        output_slices = []
        
        # Add full image first if configured (index 0)
        if include_full:
            full_encoded = self.encode_image(image, input_format)
            output_slices.append({
                'payload': {'image': full_encoded},  # Standard payload.image format
                'offset': [0, 0],
                'bbox': [0, 0, image.shape[1], image.shape[0]],
                'slice_index': 0,
                'is_full_image': True,
                'original_width': image.shape[1],
                'original_height': image.shape[0]
            })
        
        # Add slices
        start_index = 1 if include_full else 0
        for i, slice_data in enumerate(slices):
            encoded = self.encode_image(slice_data['image'], input_format)
            output_slices.append({
                'payload': {'image': encoded},  # Standard payload.image format
                'offset': slice_data['offset'],
                'bbox': slice_data['bbox'],
                'slice_index': start_index + i,
                'is_full_image': slice_data.get('is_full_image', False),
                'original_width': image.shape[1],
                'original_height': image.shape[0]
            })
        
        total_count = len(output_slices)
        
        if output_mode == 'split':
            # Send each slice as a separate message with parts metadata
            for i, slice_info in enumerate(output_slices):
                slice_msg = msg.copy()
                # Put image directly in payload for YOLO compatibility
                slice_msg['payload'] = slice_info['payload']
                slice_msg['topic'] = msg.get('topic', 'slice')
                
                # Add parts metadata for SliceCollectorNode to track
                slice_msg['parts'] = {
                    'index': i,
                    'count': total_count,
                    'id': parent_msg_id
                }
                
                # Add slice metadata at message level for SliceCollector
                slice_msg['slice_offset'] = slice_info['offset']
                slice_msg['slice_bbox'] = slice_info['bbox']
                slice_msg['slice_index'] = slice_info['slice_index']
                slice_msg['is_full_image'] = slice_info['is_full_image']
                slice_msg['original_width'] = slice_info['original_width']
                slice_msg['original_height'] = slice_info['original_height']
                
                self.send(slice_msg)
        else:
            # Array mode - send slices as array for Split node
            # Each item has 'payload' key which Split will extract
            out_msg = msg.copy()
            out_msg['payload'] = output_slices  # Direct array for Split node
            out_msg['topic'] = msg.get('topic', 'sliced')
            out_msg['slice_count'] = total_count
            out_msg['original_width'] = image.shape[1]
            out_msg['original_height'] = image.shape[0]
            out_msg['include_full_image'] = include_full
            
            self.send(out_msg)

