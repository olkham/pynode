"""
Image Format Node - converts between numpy arrays and base64 encoded images.
Supports automatic detection and manual mode selection.
"""

import base64
import copy
import cv2
import numpy as np
from typing import Any, Dict
from nodes.base_node import BaseNode


class ImageFormatNode(BaseNode):
    """
    Image Format node - converts between numpy arrays and base64 encoded images.
    """
    display_name = 'Image Format'
    icon = '🔄'
    category = 'vision'
    color = '#FFB6C1'
    border_color = '#FF69B4'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'mode': 'auto',
        'image_format': 'jpeg',
        'jpeg_quality': 85,
        'data_path': 'payload.image'
    }
    
    properties = [
        {
            'name': 'mode',
            'label': 'Conversion Mode',
            'type': 'select',
            'options': [
                {'value': 'auto', 'label': 'Auto Detect'},
                {'value': 'to_base64', 'label': 'Numpy to Base64'},
                {'value': 'to_numpy', 'label': 'Base64 to Numpy'}
            ],
            'default': DEFAULT_CONFIG['mode']
        },
        {
            'name': 'image_format',
            'label': 'Image Format',
            'type': 'select',
            'options': [
                {'value': 'jpeg', 'label': 'JPEG'},
                {'value': 'png', 'label': 'PNG'}
            ],
            'default': DEFAULT_CONFIG['image_format']
        },
        {
            'name': 'jpeg_quality',
            'label': 'JPEG Quality (1-100)',
            'type': 'number',
            'default': DEFAULT_CONFIG['jpeg_quality']
        },
        {
            'name': 'data_path',
            'label': 'Data Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['data_path'],
            'description': 'Dot-separated path to image data (e.g. payload.image)'
        }
    ]
    
    def __init__(self, node_id=None, name="image format"):
        super().__init__(node_id, name)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Convert image data between numpy array and base64.
        """
        mode = self.config.get('mode', 'auto')
        data_path = self.config.get('data_path', 'payload')
        
        # Get data from message
        def get_by_path(obj, path):
            parts = path.split('.')
            for part in parts:
                if isinstance(obj, dict) and part in obj:
                    obj = obj[part]
                else:
                    return None
            return obj
        
        data = get_by_path(msg, data_path)
        
        if data is None:
            self.report_error(f"No data found at path '{data_path}'")
            return
        
        # Auto-detect mode
        if mode == 'auto':
            if isinstance(data, np.ndarray):
                mode = 'to_base64'
            elif isinstance(data, dict) and data.get('encoding') == 'base64':
                mode = 'to_numpy'
            elif isinstance(data, str):
                mode = 'to_numpy'
            else:
                self.report_error(f"Cannot auto-detect conversion mode for type: {type(data)}")
                return
        
        # Perform conversion
        try:
            output_msg = copy.deepcopy(msg)
            
            # Get the target object where we'll update fields
            def get_parent_and_key(obj, path):
                parts = path.split('.')
                if len(parts) == 1:
                    return obj, parts[0]
                for part in parts[:-1]:
                    if part not in obj or not isinstance(obj[part], dict):
                        obj[part] = {}
                    obj = obj[part]
                return obj, parts[-1]
            
            parent, key = get_parent_and_key(output_msg, data_path)
            
            if mode == 'to_base64':
                # Get the numpy array from the data
                if isinstance(data, dict) and 'data' in data:
                    numpy_data = data['data']
                else:
                    numpy_data = data
                
                # Convert to base64
                converted = self._numpy_to_base64(numpy_data)
                
                # Update the target dict in place if it exists and has the right structure
                if key in parent and isinstance(parent[key], dict):
                    parent[key]['format'] = converted['format']
                    parent[key]['encoding'] = converted['encoding']
                    parent[key]['data'] = converted['data']
                    parent[key]['width'] = converted['width']
                    parent[key]['height'] = converted['height']
                else:
                    parent[key] = converted
                    
            elif mode == 'to_numpy':
                # Convert to numpy
                numpy_array = self._base64_to_numpy(data)
                
                # Update the target dict in place if it exists
                if key in parent and isinstance(parent[key], dict):
                    parent[key]['format'] = 'bgr'
                    parent[key]['encoding'] = 'numpy'
                    parent[key]['data'] = numpy_array
                    parent[key]['width'] = numpy_array.shape[1]
                    parent[key]['height'] = numpy_array.shape[0]
                else:
                    parent[key] = {
                        'format': 'bgr',
                        'encoding': 'numpy',
                        'data': numpy_array,
                        'width': numpy_array.shape[1],
                        'height': numpy_array.shape[0]
                    }
            else:
                self.report_error(f"Unknown mode: {mode}")
                return
            
            self.send(output_msg)
            
        except Exception as e:
            self.report_error(f"Conversion error: {e}")
    
    def _numpy_to_base64(self, image: np.ndarray) -> Dict[str, Any]:
        """Convert numpy array to base64 encoded image."""
        if not isinstance(image, np.ndarray):
            raise ValueError(f"Expected numpy array, got {type(image)}")
        
        img_format = self.config.get('image_format', 'jpeg')
        
        if img_format == 'jpeg':
            quality = self.get_config_int('jpeg_quality', 85)
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
            ret, buffer = cv2.imencode('.jpg', image, encode_params)
            ext = 'jpeg'
        elif img_format == 'png':
            ret, buffer = cv2.imencode('.png', image)
            ext = 'png'
        else:
            raise ValueError(f"Unsupported format: {img_format}")
        
        if not ret:
            raise RuntimeError("Failed to encode image")
        
        # Convert to base64
        img_base64 = base64.b64encode(buffer.tobytes()).decode('utf-8')
        
        return {
            'format': ext,
            'encoding': 'base64',
            'data': img_base64,
            'width': image.shape[1],
            'height': image.shape[0]
        }
    
    def _base64_to_numpy(self, data: Any) -> np.ndarray:
        """Convert base64 encoded image to numpy array."""
        # Handle dict format
        if isinstance(data, dict):
            img_data = data.get('data')
            if img_data is None:
                raise ValueError("No 'data' field in image dict")
        # Handle raw base64 string
        elif isinstance(data, str):
            img_data = data
            # Remove data URL prefix if present
            if img_data.startswith('data:image'):
                img_data = img_data.split(',')[1]
        else:
            raise ValueError(f"Cannot convert {type(data)} to numpy array")
        
        # Decode base64
        try:
            img_bytes = base64.b64decode(img_data)
            nparr = np.frombuffer(img_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if image is None:
                raise RuntimeError("Failed to decode image")
            
            return image
        except Exception as e:
            raise RuntimeError(f"Failed to decode base64 image: {e}")
