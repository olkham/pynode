"""
Colormap Node - applies colormaps to depth/grayscale images for visualization.
"""

import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class ColormapNode(BaseNode):
    """
    Colormap node - applies OpenCV colormaps to depth or grayscale images.
    Useful for visualizing depth maps, heatmaps, and other single-channel data.
    """
    display_name = 'Colormap'
    icon = '🎨'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'input_source': 'depth',
        'colormap': 'jet',
        'alpha': 0.03,
        'auto_scale': 'false',
        'min_value': 0,
        'max_value': 0,
        'invert': 'false'
    }
    
    properties = [
        {
            'name': 'input_source',
            'label': 'Input Source',
            'type': 'select',
            'options': [
                {'value': 'image', 'label': 'From msg.payload.image'},
                {'value': 'depth', 'label': 'From msg.payload.depth'}
            ],
            'default': DEFAULT_CONFIG['input_source'],
            'help': 'Source of the grayscale/depth data'
        },
        {
            'name': 'colormap',
            'label': 'Colormap',
            'type': 'select',
            'options': [
                {'value': 'jet', 'label': 'Jet'},
                {'value': 'turbo', 'label': 'Turbo'},
                {'value': 'viridis', 'label': 'Viridis'},
                {'value': 'plasma', 'label': 'Plasma'},
                {'value': 'inferno', 'label': 'Inferno'},
                {'value': 'magma', 'label': 'Magma'},
                {'value': 'hot', 'label': 'Hot'},
                {'value': 'bone', 'label': 'Bone'},
                {'value': 'cool', 'label': 'Cool'},
                {'value': 'spring', 'label': 'Spring'},
                {'value': 'summer', 'label': 'Summer'},
                {'value': 'autumn', 'label': 'Autumn'},
                {'value': 'winter', 'label': 'Winter'},
                {'value': 'rainbow', 'label': 'Rainbow'},
                {'value': 'ocean', 'label': 'Ocean'},
                {'value': 'parula', 'label': 'Parula'},
                {'value': 'pink', 'label': 'Pink'},
                {'value': 'hsv', 'label': 'HSV'},
                {'value': 'twilight', 'label': 'Twilight'},
                {'value': 'twilight_shifted', 'label': 'Twilight Shifted'},
                {'value': 'deepgreen', 'label': 'Deep Green'}
            ],
            'default': DEFAULT_CONFIG['colormap'],
            'help': 'Colormap to apply'
        },
        {
            'name': 'alpha',
            'label': 'Scale (alpha)',
            'type': 'number',
            'default': DEFAULT_CONFIG['alpha'],
            'min': 0.001,
            'max': 1.0,
            'step': 0.005,
            'help': 'Scale factor for depth/intensity conversion (higher = more contrast)'
        },
        {
            'name': 'auto_scale',
            'label': 'Auto Scale',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes (normalize to full range)'},
                {'value': 'false', 'label': 'No (use alpha scale)'}
            ],
            'default': DEFAULT_CONFIG['auto_scale'],
            'help': 'Automatically normalize values to 0-255 range'
        },
        {
            'name': 'min_value',
            'label': 'Min Value (for auto-scale)',
            'type': 'number',
            'default': DEFAULT_CONFIG['min_value'],
            'help': 'Minimum value for normalization (0 = auto detect)'
        },
        {
            'name': 'max_value',
            'label': 'Max Value (for auto-scale)',
            'type': 'number',
            'default': DEFAULT_CONFIG['max_value'],
            'help': 'Maximum value for normalization (0 = auto detect)'
        },
        {
            'name': 'invert',
            'label': 'Invert',
            'type': 'select',
            'options': [
                {'value': 'false', 'label': 'No'},
                {'value': 'true', 'label': 'Yes'}
            ],
            'default': DEFAULT_CONFIG['invert'],
            'help': 'Invert the colormap (flip colors)'
        }
    ]
    
    # Colormap lookup
    COLORMAPS = {
        'jet': cv2.COLORMAP_JET,
        'turbo': cv2.COLORMAP_TURBO,
        'viridis': cv2.COLORMAP_VIRIDIS,
        'plasma': cv2.COLORMAP_PLASMA,
        'inferno': cv2.COLORMAP_INFERNO,
        'magma': cv2.COLORMAP_MAGMA,
        'hot': cv2.COLORMAP_HOT,
        'bone': cv2.COLORMAP_BONE,
        'cool': cv2.COLORMAP_COOL,
        'spring': cv2.COLORMAP_SPRING,
        'summer': cv2.COLORMAP_SUMMER,
        'autumn': cv2.COLORMAP_AUTUMN,
        'winter': cv2.COLORMAP_WINTER,
        'rainbow': cv2.COLORMAP_RAINBOW,
        'ocean': cv2.COLORMAP_OCEAN,
        'parula': cv2.COLORMAP_PARULA,
        'pink': cv2.COLORMAP_PINK,
        'hsv': cv2.COLORMAP_HSV,
        'twilight': cv2.COLORMAP_TWILIGHT,
        'twilight_shifted': cv2.COLORMAP_TWILIGHT_SHIFTED,
        'deepgreen': cv2.COLORMAP_DEEPGREEN
    }
    
    def __init__(self, node_id=None, name="colormap"):
        super().__init__(node_id, name)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Apply colormap to input image/depth data."""
        payload = msg.get('payload')
        if not payload:
            self.report_error("No payload found")
            return
        
        input_source = self.config.get('input_source', 'depth')
        format_type = 'numpy_array'
        input_image = None
        
        if isinstance(payload, dict):
            if input_source == 'depth' and 'depth' in payload:
                # Get depth data
                depth_data = payload['depth']
                if isinstance(depth_data, np.ndarray):
                    input_image = depth_data
                elif isinstance(depth_data, dict) and 'data' in depth_data:
                    input_image = np.array(depth_data['data'])
            elif 'image' in payload:
                # Get image data
                img, format_type = self.decode_image(payload)
                if img is not None:
                    input_image = img
        elif isinstance(payload, np.ndarray):
            input_image = payload
        
        if input_image is None:
            self.report_error(f"No valid {input_source} data found in payload")
            return
        
        # Convert to grayscale if needed
        if len(input_image.shape) == 3:
            input_image = cv2.cvtColor(input_image, cv2.COLOR_BGR2GRAY)
        
        # Get configuration
        colormap_name = self.config.get('colormap', 'jet')
        alpha = self.get_config_float('alpha', 0.03)
        auto_scale = self.get_config_bool('auto_scale', False)
        min_value = self.get_config_float('min_value', 0)
        max_value = self.get_config_float('max_value', 0)
        invert = self.get_config_bool('invert', False)
        
        colormap = self.COLORMAPS.get(colormap_name, cv2.COLORMAP_JET)
        
        # Convert to 8-bit for colormap
        if auto_scale:
            # Auto-normalize to 0-255
            if min_value == 0 and max_value == 0:
                # Auto-detect range
                valid_mask = input_image > 0  # Ignore zeros (often invalid depth)
                if np.any(valid_mask):
                    min_val = np.min(input_image[valid_mask])
                    max_val = np.max(input_image[valid_mask])
                else:
                    min_val = np.min(input_image)
                    max_val = np.max(input_image)
            else:
                min_val = min_value
                max_val = max_value
            
            if max_val > min_val:
                normalized = ((input_image.astype(np.float32) - min_val) / (max_val - min_val) * 255)
                normalized = np.clip(normalized, 0, 255).astype(np.uint8)
            else:
                normalized = np.zeros_like(input_image, dtype=np.uint8)
        else:
            # Use alpha scaling
            normalized = cv2.convertScaleAbs(input_image, alpha=alpha)
        
        # Invert if requested
        if invert:
            normalized = 255 - normalized
        
        # Apply colormap
        colorized = cv2.applyColorMap(normalized, colormap)
        
        # Prepare output
        if not isinstance(msg.get('payload'), dict):
            msg['payload'] = {}
        
        msg['payload']['image'] = self.encode_image(colorized, format_type)
        
        # Add metadata
        msg['colormap'] = {
            'applied': colormap_name,
            'auto_scale': auto_scale,
            'invert': invert,
            'input_dtype': str(input_image.dtype),
            'input_shape': list(input_image.shape)
        }
        
        self.send(msg)
