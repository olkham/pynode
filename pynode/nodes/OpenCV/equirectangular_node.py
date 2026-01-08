"""
Equirectangular to Pinhole Projection Node - converts 360° equirectangular images to standard pinhole camera views.
Uses optimized Numba JIT compilation for high-performance coordinate mapping.
"""

import math
import cv2
import numpy as np
from typing import Any, Dict, Tuple
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Converts 360° equirectangular images to standard pinhole camera perspective views. Uses optimized Numba JIT compilation for high-performance coordinate mapping when available.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Equirectangular (360°) image frame")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Projected pinhole camera view image")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Yaw:", "Horizontal rotation angle (-180° to 180°)"),
    ("Pitch:", "Vertical rotation angle (-90° to 90°)"),
    ("Roll:", "Rotation around view axis (-180° to 180°)"),
    ("FOV:", "Field of view in degrees (1° to 179°)"),
    ("Output Width/Height:", "Resolution of the projected output image"),
    ("Angle Source:", "Use config values or read from msg.angles"),
    ("Interpolation:", "Nearest, Linear, or Cubic sampling")
)

# Check for Numba availability
try:
    from numba import njit, prange
    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False


# Numba JIT-compiled functions for maximum performance
if _HAS_NUMBA:
    @njit(cache=True, fastmath=True)
    def _generate_mapping_jit(output_width, output_height, focal_length, cx, cy,
                              R00, R01, R02, R10, R11, R12, R20, R21, R22,
                              frame_height, frame_width):
        """JIT-compiled coordinate mapping generation for maximum speed"""
        pixel_x = np.empty((output_height, output_width), dtype=np.float32)
        pixel_y = np.empty((output_height, output_width), dtype=np.float32)
        
        inv_focal = 1.0 / focal_length
        inv_2pi = 1.0 / (2.0 * np.pi)
        inv_pi = 1.0 / np.pi
        half_pi = np.pi * 0.5
        frame_width_minus_1 = frame_width - 1
        frame_height_minus_1 = frame_height - 1
        
        for j in range(output_height):
            y_norm = (j - cy) * inv_focal
            for i in range(output_width):
                x_norm = (i - cx) * inv_focal
                
                norm_factor = 1.0 / math.sqrt(x_norm * x_norm + y_norm * y_norm + 1.0)
                x_unit = x_norm * norm_factor
                y_unit = y_norm * norm_factor
                z_unit = norm_factor
                
                x_rot = R00 * x_unit + R01 * y_unit + R02 * z_unit
                y_rot = R10 * x_unit + R11 * y_unit + R12 * z_unit
                z_rot = R20 * x_unit + R21 * y_unit + R22 * z_unit
                
                theta = math.atan2(x_rot, z_rot)
                phi = math.asin(max(-1.0, min(1.0, y_rot)))
                
                u = (theta + np.pi) * inv_2pi
                v = (phi + half_pi) * inv_pi
                
                pixel_x[j, i] = max(0.0, min(frame_width_minus_1, u * frame_width_minus_1))
                pixel_y[j, i] = max(0.0, min(frame_height_minus_1, v * frame_height_minus_1))
        
        return pixel_x, pixel_y

    @njit(cache=True, fastmath=True, parallel=True)
    def _generate_mapping_jit_parallel(output_width, output_height, focal_length, cx, cy,
                                       R00, R01, R02, R10, R11, R12, R20, R21, R22,
                                       frame_height, frame_width):
        """Parallel JIT-compiled coordinate mapping for multi-core systems"""
        pixel_x = np.empty((output_height, output_width), dtype=np.float32)
        pixel_y = np.empty((output_height, output_width), dtype=np.float32)
        
        inv_focal = 1.0 / focal_length
        inv_2pi = 0.15915494309189535
        inv_pi = 0.3183098861837907
        half_pi = 1.5707963267948966
        frame_width_f = float(frame_width - 1)
        frame_height_f = float(frame_height - 1)
        pi = 3.141592653589793
        
        total_pixels = output_height * output_width
        
        for idx in prange(total_pixels):
            j = idx // output_width
            i = idx % output_width
            
            x_norm = (i - cx) * inv_focal
            y_norm = (j - cy) * inv_focal
            
            norm_factor = 1.0 / math.sqrt(x_norm * x_norm + y_norm * y_norm + 1.0)
            x_unit = x_norm * norm_factor
            y_unit = y_norm * norm_factor
            z_unit = norm_factor
            
            x_rot = R00 * x_unit + R01 * y_unit + R02 * z_unit
            y_rot = R10 * x_unit + R11 * y_unit + R12 * z_unit
            z_rot = R20 * x_unit + R21 * y_unit + R22 * z_unit
            
            theta = math.atan2(x_rot, z_rot)
            phi = math.asin(max(-1.0, min(1.0, y_rot)))
            
            u = (theta + pi) * inv_2pi
            v = (phi + half_pi) * inv_pi
            
            pixel_x[j, i] = max(0.0, min(frame_width_f, u * frame_width_f))
            pixel_y[j, i] = max(0.0, min(frame_height_f, v * frame_height_f))
        
        return pixel_x, pixel_y


class EquirectangularNode(BaseNode):
    """
    Equirectangular to Pinhole Projection node - converts 360° equirectangular images
    to standard pinhole camera perspective views with configurable yaw, pitch, roll, and FOV.
    """
    info = str(_info)
    display_name = 'Equirectangular'
    icon = '🌐'
    category = 'opencv'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'yaw': 0,
        'pitch': 0,
        'roll': 0,
        'fov': 90,
        'output_width': 1920,
        'output_height': 1080,
        'angle_source': 'config',
        'interpolation': 'linear'
    }
    
    properties = [
        {
            'name': 'yaw',
            'label': 'Yaw (°)',
            'type': 'number',
            'default': DEFAULT_CONFIG['yaw'],
            'min': -180,
            'max': 180,
            'step': 1,
            'help': 'Horizontal rotation (-180 to 180)'
        },
        {
            'name': 'pitch',
            'label': 'Pitch (°)',
            'type': 'number',
            'default': DEFAULT_CONFIG['pitch'],
            'min': -90,
            'max': 90,
            'step': 1,
            'help': 'Vertical rotation (-90 to 90)'
        },
        {
            'name': 'roll',
            'label': 'Roll (°)',
            'type': 'number',
            'default': DEFAULT_CONFIG['roll'],
            'min': -180,
            'max': 180,
            'step': 1,
            'help': 'Roll rotation (-180 to 180)'
        },
        {
            'name': 'fov',
            'label': 'Field of View (°)',
            'type': 'number',
            'default': DEFAULT_CONFIG['fov'],
            'min': 10,
            'max': 170,
            'step': 5,
            'help': 'Field of view angle'
        },
        {
            'name': 'output_width',
            'label': 'Output Width',
            'type': 'number',
            'default': DEFAULT_CONFIG['output_width'],
            'min': 64,
            'max': 4096,
            'help': 'Width of output image'
        },
        {
            'name': 'output_height',
            'label': 'Output Height',
            'type': 'number',
            'default': DEFAULT_CONFIG['output_height'],
            'min': 64,
            'max': 4096,
            'help': 'Height of output image'
        },
        {
            'name': 'angle_source',
            'label': 'Angle Source',
            'type': 'select',
            'options': [
                {'value': 'config', 'label': 'From config'},
                {'value': 'msg', 'label': 'From message (msg.yaw, msg.pitch, msg.roll)'}
            ],
            'default': DEFAULT_CONFIG['angle_source'],
            'help': 'Source for yaw/pitch/roll values'
        },
        {
            'name': 'interpolation',
            'label': 'Interpolation',
            'type': 'select',
            'options': [
                {'value': 'linear', 'label': 'Bilinear (fast)'},
                {'value': 'cubic', 'label': 'Bicubic (quality)'},
                {'value': 'lanczos', 'label': 'Lanczos (best quality)'}
            ],
            'default': DEFAULT_CONFIG['interpolation'],
            'help': 'Interpolation method for remapping'
        }
    ]
    
    def __init__(self, node_id=None, name="equirectangular"):
        super().__init__(node_id, name)
        
        # Coordinate mapping cache
        self._map_cache = {}
        self._cache_size_limit = 20
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Convert equirectangular image to pinhole projection."""
        if 'payload' not in msg:
            self.send(msg)
            return
        
        # Decode image from any supported format
        img, format_type = self.decode_image(msg['payload'])
        if img is None:
            self.report_error("Could not decode image from payload")
            self.send(msg)
            return
        
        # Get angles from config or message
        angle_source = self.config.get('angle_source', 'config')
        if angle_source == 'msg':
            yaw = float(msg.get('yaw', self.config.get('yaw', 0)))
            pitch = float(msg.get('pitch', self.config.get('pitch', 0)))
            roll = float(msg.get('roll', self.config.get('roll', 0)))
        else:
            yaw = self.get_config_float('yaw', 0)
            pitch = self.get_config_float('pitch', 0)
            roll = self.get_config_float('roll', 0)
        
        fov = self.get_config_float('fov', 90)
        output_width = self.get_config_int('output_width', 1920)
        output_height = self.get_config_int('output_height', 1080)
        
        # Normalize angles for consistent caching
        norm_yaw, norm_pitch, norm_roll = self._normalize_angles(yaw, pitch, roll)
        
        # Create cache key
        cache_key = (norm_yaw, norm_pitch, norm_roll, fov, output_width, output_height, 
                     img.shape[0], img.shape[1])
        
        # Check cache for coordinate mapping
        if cache_key in self._map_cache:
            pixel_x, pixel_y = self._map_cache[cache_key]
        else:
            # Generate new mapping
            pixel_x, pixel_y = self._generate_coordinate_mapping(
                norm_yaw, norm_pitch, norm_roll, fov, output_width, output_height, img.shape
            )
            
            # Cache management
            if len(self._map_cache) >= self._cache_size_limit:
                oldest_key = next(iter(self._map_cache))
                del self._map_cache[oldest_key]
            
            self._map_cache[cache_key] = (pixel_x, pixel_y)
        
        # Get interpolation method
        interp_str = self.config.get('interpolation', 'linear')
        interp_map = {
            'linear': cv2.INTER_LINEAR,
            'cubic': cv2.INTER_CUBIC,
            'lanczos': cv2.INTER_LANCZOS4
        }
        interpolation = interp_map.get(interp_str, cv2.INTER_LINEAR)
        
        # Apply remapping
        result = cv2.remap(img, pixel_x, pixel_y, interpolation, borderMode=cv2.BORDER_WRAP)
        
        # Encode back to original format
        if 'payload' not in msg or not isinstance(msg['payload'], dict):
            msg['payload'] = {}
        msg['payload']['image'] = self.encode_image(result, format_type)
        
        # Add projection info to message
        msg['projection'] = {
            'yaw': yaw,
            'pitch': pitch,
            'roll': roll,
            'fov': fov,
            'output_size': [output_width, output_height]
        }
        
        self.send(msg)
    
    def _generate_coordinate_mapping(self, yaw: float, pitch: float, roll: float, fov: float,
                                     output_width: int, output_height: int, 
                                     frame_shape: Tuple[int, ...]) -> Tuple[np.ndarray, np.ndarray]:
        """Generate coordinate mapping for equirectangular to pinhole projection."""
        # Convert to radians
        yaw_rad = math.radians(yaw)
        pitch_rad = math.radians(pitch)
        roll_rad = math.radians(roll)
        fov_rad = math.radians(fov)
        
        # Calculate focal length and center
        focal_length = output_width / (2 * math.tan(fov_rad / 2))
        cx = output_width * 0.5
        cy = output_height * 0.5
        
        # Create rotation matrix elements
        cos_r, sin_r = math.cos(roll_rad), math.sin(roll_rad)
        cos_p, sin_p = math.cos(pitch_rad), math.sin(pitch_rad)
        cos_y, sin_y = math.cos(yaw_rad), math.sin(yaw_rad)
        
        # Combined rotation matrix elements
        R00 = cos_y * cos_r + sin_y * sin_r * sin_p
        R01 = cos_y * (-sin_r) + sin_y * cos_r * sin_p
        R02 = sin_y * cos_p
        R10 = sin_r * cos_p
        R11 = cos_r * cos_p
        R12 = -sin_p
        R20 = -sin_y * cos_r + cos_y * sin_r * sin_p
        R21 = -sin_y * (-sin_r) + cos_y * cos_r * sin_p
        R22 = cos_y * cos_p
        
        # Choose implementation based on Numba availability and output size
        total_pixels = output_width * output_height
        
        if _HAS_NUMBA:
            if total_pixels > 500000:
                return _generate_mapping_jit_parallel(
                    output_width, output_height, focal_length, cx, cy,
                    R00, R01, R02, R10, R11, R12, R20, R21, R22,
                    frame_shape[0], frame_shape[1]
                )
            else:
                return _generate_mapping_jit(
                    output_width, output_height, focal_length, cx, cy,
                    R00, R01, R02, R10, R11, R12, R20, R21, R22,
                    frame_shape[0], frame_shape[1]
                )
        else:
            # Pure NumPy fallback (slower but works without Numba)
            return self._generate_mapping_numpy(
                output_width, output_height, focal_length, cx, cy,
                R00, R01, R02, R10, R11, R12, R20, R21, R22,
                frame_shape[0], frame_shape[1]
            )
    
    def _generate_mapping_numpy(self, output_width, output_height, focal_length, cx, cy,
                                R00, R01, R02, R10, R11, R12, R20, R21, R22,
                                frame_height, frame_width):
        """Pure NumPy fallback for coordinate mapping (no Numba required)."""
        # Create coordinate grids
        i_coords = np.arange(output_width, dtype=np.float32)
        j_coords = np.arange(output_height, dtype=np.float32)
        i_grid, j_grid = np.meshgrid(i_coords, j_coords)
        
        # Normalize coordinates
        x_norm = (i_grid - cx) / focal_length
        y_norm = (j_grid - cy) / focal_length
        
        # Normalize direction vectors
        norm_factor = 1.0 / np.sqrt(x_norm**2 + y_norm**2 + 1.0)
        x_unit = x_norm * norm_factor
        y_unit = y_norm * norm_factor
        z_unit = norm_factor
        
        # Apply rotation matrix
        x_rot = R00 * x_unit + R01 * y_unit + R02 * z_unit
        y_rot = R10 * x_unit + R11 * y_unit + R12 * z_unit
        z_rot = R20 * x_unit + R21 * y_unit + R22 * z_unit
        
        # Convert to spherical coordinates
        theta = np.arctan2(x_rot, z_rot)
        phi = np.arcsin(np.clip(y_rot, -1.0, 1.0))
        
        # Convert to pixel coordinates
        u = (theta + np.pi) / (2 * np.pi)
        v = (phi + np.pi / 2) / np.pi
        
        pixel_x = np.clip(u * (frame_width - 1), 0, frame_width - 1).astype(np.float32)
        pixel_y = np.clip(v * (frame_height - 1), 0, frame_height - 1).astype(np.float32)
        
        return pixel_x, pixel_y
    
    def _normalize_angles(self, yaw: float, pitch: float, roll: float) -> Tuple[float, float, float]:
        """Normalize angles to canonical ranges for cache consistency."""
        # Normalize yaw to [0, 360)
        yaw = yaw % 360
        
        # Normalize pitch properly
        pitch = ((pitch + 180) % 360) - 180
        
        # Handle pitch overflow beyond valid range [-90, 90]
        if pitch > 90:
            pitch = 180 - pitch
            yaw = (yaw + 180) % 360
            roll = (roll + 180) % 360
        elif pitch < -90:
            pitch = -180 - pitch
            yaw = (yaw + 180) % 360
            roll = (roll + 180) % 360
        
        # Normalize roll to [0, 360)
        roll = roll % 360
        
        return yaw, pitch, roll
    
    def clear_cache(self):
        """Clear the coordinate mapping cache."""
        self._map_cache.clear()
    
    def on_stop(self):
        """Clean up when node is stopped."""
        self.clear_cache()
        super().on_stop()
