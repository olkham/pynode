"""
RealSense Depth Processing Node - processes RealSense depth camera frames.
Handles aligned RGB and depth data with various output formats.
"""

import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Processes Intel RealSense depth camera frames. Handles aligned RGB and depth data with various output format options.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "RealSense frame with aligned_color and aligned_depth data, or image with depth payload")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Processed frame based on output format setting")
)
_info.add_header("Output Formats")
_info.add_bullets(
    ("RGB only:", "Color image only"),
    ("Depth only:", "Raw 16-bit depth data"),
    ("Depth colorized:", "Depth mapped to colormap"),
    ("Side by side:", "RGB and colorized depth horizontally combined"),
    ("Both:", "Separate RGB and depth in payload")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Depth Scale:", "Alpha value for depth visualization contrast (0.001-1.0)"),
    ("Colormap:", "Color scheme for depth visualization (Jet, Turbo, Viridis, etc.)")
)


class RealsenseDepthNode(BaseNode):
    """
    RealSense Depth Processing node - processes depth camera frames from RealSense cameras.
    Expects input with aligned_color and aligned_depth frame data.
    Outputs RGB, depth, colorized depth, or combined formats.
    """
    info = str(_info)
    display_name = 'RealSense Depth'
    icon = '📷'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'output_format': 'both',
        'depth_scale': 0.03,
        'colormap': 'jet'
    }
    
    properties = [
        {
            'name': 'output_format',
            'label': 'Output Format',
            'type': 'select',
            'options': [
                {'value': 'rgb', 'label': 'RGB only'},
                {'value': 'depth', 'label': 'Depth only (raw)'},
                {'value': 'depth_colorized', 'label': 'Depth colorized'},
                {'value': 'side_by_side', 'label': 'Side by side (RGB + Depth)'},
                {'value': 'both', 'label': 'Both (separate in payload)'}
            ],
            'default': DEFAULT_CONFIG['output_format'],
            'help': 'Output format for processed frames'
        },
        {
            'name': 'depth_scale',
            'label': 'Depth Scale (alpha)',
            'type': 'number',
            'default': DEFAULT_CONFIG['depth_scale'],
            'min': 0.001,
            'max': 1.0,
            'step': 0.005,
            'help': 'Scale factor for depth visualization (higher = more contrast)'
        },
        {
            'name': 'colormap',
            'label': 'Depth Colormap',
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
                {'value': 'rainbow', 'label': 'Rainbow'}
            ],
            'default': DEFAULT_CONFIG['colormap'],
            'help': 'Colormap for depth visualization'
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
        'rainbow': cv2.COLORMAP_RAINBOW
    }
    
    def __init__(self, node_id=None, name="realsense depth"):
        super().__init__(node_id, name)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Process RealSense depth camera frames."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        payload = msg['payload']
        
        # Handle different input formats
        color_image = None
        depth_image = None
        format_type = 'numpy_array'
        
        # Check for RealSense frame dict format (from FrameSource)
        if isinstance(payload, dict):
            # Try to get aligned frames (pyrealsense2 format)
            if 'aligned_color' in payload and 'aligned_depth' in payload:
                aligned_color = payload['aligned_color']
                aligned_depth = payload['aligned_depth']
                
                # Handle pyrealsense2 frame objects
                if hasattr(aligned_color, 'get_data'):
                    color_image = np.asanyarray(aligned_color.get_data())
                elif isinstance(aligned_color, np.ndarray):
                    color_image = aligned_color
                
                if hasattr(aligned_depth, 'get_data'):
                    depth_image = np.asanyarray(aligned_depth.get_data())
                elif isinstance(aligned_depth, np.ndarray):
                    depth_image = aligned_depth
            
            # Try standard image + depth format
            elif 'image' in payload:
                img, format_type = self.decode_image(payload)
                if img is not None:
                    color_image = img
                
                if 'depth' in payload:
                    depth_data = payload['depth']
                    if isinstance(depth_data, np.ndarray):
                        depth_image = depth_data
                    elif isinstance(depth_data, dict) and 'data' in depth_data:
                        depth_image = np.array(depth_data['data'], dtype=np.uint16)
        
        # Handle direct numpy array (assume it's color)
        elif isinstance(payload, np.ndarray):
            color_image = payload
        
        if color_image is None and depth_image is None:
            self.report_error("No valid color or depth data found in payload")
            self.send(msg)
            return
        
        # Get configuration
        output_format = self.config.get('output_format', 'both')
        depth_scale = self.get_config_float('depth_scale', 0.03)
        colormap_name = self.config.get('colormap', 'jet')
        colormap = self.COLORMAPS.get(colormap_name, cv2.COLORMAP_JET)
        
        # Create colorized depth if needed
        depth_colorized = None
        if depth_image is not None and output_format in ['depth_colorized', 'side_by_side', 'both']:
            depth_8bit = cv2.convertScaleAbs(depth_image, alpha=depth_scale)
            depth_colorized = cv2.applyColorMap(depth_8bit, colormap)
        
        # Prepare output based on format
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        
        if output_format == 'rgb':
            if color_image is not None:
                msg['payload']['image'] = self.encode_image(color_image, format_type)
            else:
                self.report_error("No color image available for RGB output")
                return
        
        elif output_format == 'depth':
            if depth_image is not None:
                # Output raw depth as-is (16-bit typically)
                msg['payload']['depth'] = depth_image
                msg['payload']['depth_info'] = {
                    'width': depth_image.shape[1],
                    'height': depth_image.shape[0],
                    'dtype': str(depth_image.dtype)
                }
            else:
                self.report_error("No depth image available")
                return
        
        elif output_format == 'depth_colorized':
            if depth_colorized is not None:
                msg['payload']['image'] = self.encode_image(depth_colorized, format_type)
            else:
                self.report_error("No depth image available for colorization")
                return
        
        elif output_format == 'side_by_side':
            if color_image is not None and depth_colorized is not None:
                # Resize if dimensions don't match
                if color_image.shape[:2] != depth_colorized.shape[:2]:
                    depth_colorized = cv2.resize(
                        depth_colorized,
                        (color_image.shape[1], color_image.shape[0]),
                        interpolation=cv2.INTER_AREA
                    )
                combined = np.hstack((color_image, depth_colorized))
                msg['payload']['image'] = self.encode_image(combined, format_type)
            else:
                self.report_error("Both color and depth required for side-by-side output")
                return
        
        elif output_format == 'both':
            # Output both RGB and depth in payload
            if color_image is not None:
                msg['payload']['image'] = self.encode_image(color_image, format_type)
            if depth_image is not None:
                msg['payload']['depth'] = depth_image
                msg['payload']['depth_info'] = {
                    'width': depth_image.shape[1],
                    'height': depth_image.shape[0],
                    'dtype': str(depth_image.dtype)
                }
            if depth_colorized is not None:
                msg['payload']['depth_colorized'] = self.encode_image(depth_colorized, format_type)
        
        # Add metadata
        msg['realsense'] = {
            'output_format': output_format,
            'has_color': color_image is not None,
            'has_depth': depth_image is not None,
            'color_shape': list(color_image.shape) if color_image is not None else None,
            'depth_shape': list(depth_image.shape) if depth_image is not None else None
        }
        
        self.send(msg)
