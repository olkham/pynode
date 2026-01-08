"""
Image Format Node - converts between numpy arrays and base64 encoded images.
Supports automatic detection and manual mode selection.
"""

import base64
import copy
import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Converts image data between numpy arrays and base64 encoded images. Supports automatic format detection.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with image data at the configured data path.")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Message with converted image data.")
)
_info.add_header("Conversion Modes")
_info.add_bullets(
    ("Auto Detect:", "Automatically detect source format and convert."),
    ("Numpy to Base64:", "Convert numpy array to base64 JPEG/PNG string."),
    ("Base64 to Numpy:", "Decode base64 string to numpy array (BGR format).")
)
_info.add_header("Image Formats")
_info.add_bullets(
    ("JPEG:", "Lossy compression, smaller size, configurable quality."),
    ("PNG:", "Lossless compression, larger size, preserves all data.")
)


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
    info = str(_info)
    
    DEFAULT_CONFIG = {
        'mode': 'auto',
        MessageKeys.IMAGE.FORMAT: 'jpeg',
        MessageKeys.IMAGE.JPEG_QUALITY: 85,
        'data_path': f'{MessageKeys.PAYLOAD}.{MessageKeys.IMAGE.PATH}'
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
            'name': MessageKeys.IMAGE.FORMAT,
            'label': 'Image Format',
            'type': 'select',
            'options': [
                {'value': 'jpeg', 'label': 'JPEG'},
                {'value': 'png', 'label': 'PNG'}
            ],
            'default': DEFAULT_CONFIG[MessageKeys.IMAGE.FORMAT]
        },
        {
            'name': MessageKeys.IMAGE.JPEG_QUALITY,
            'label': 'JPEG Quality (1-100)',
            'type': 'number',
            'default': DEFAULT_CONFIG[MessageKeys.IMAGE.JPEG_QUALITY]
        },
        {
            'name': 'data_path',
            'label': 'Data Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['data_path'],
            'description': f'Dot-separated path to image data (e.g. {MessageKeys.PAYLOAD}.{MessageKeys.IMAGE.PATH})'
        }
    ]
    
    def __init__(self, node_id=None, name="image format"):
        super().__init__(node_id, name)
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Convert image data between numpy array and base64.
        """
        mode = self.config.get('mode', 'auto')
        data_path = self.config.get('data_path', MessageKeys.PAYLOAD)
        
        data = self._get_nested_value(msg, data_path)
        
        if data is None:
            self.report_error(f"No data found at path '{data_path}'")
            return
        
        # Auto-detect mode
        if mode == 'auto':
            if isinstance(data, np.ndarray):
                mode = 'to_base64'
            elif isinstance(data, dict) and data.get(MessageKeys.IMAGE.ENCODING) == 'base64':
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
                if isinstance(data, dict) and MessageKeys.IMAGE.DATA in data:
                    numpy_data = data[MessageKeys.IMAGE.DATA]
                else:
                    numpy_data = data
                
                # Convert to base64
                converted = self._numpy_to_base64(numpy_data)
                
                # Update the target dict in place if it exists and has the right structure
                if key in parent and isinstance(parent[key], dict):
                    parent[key][MessageKeys.IMAGE.FORMAT] = converted[MessageKeys.IMAGE.FORMAT]
                    parent[key][MessageKeys.IMAGE.ENCODING] = converted[MessageKeys.IMAGE.ENCODING]
                    parent[key][MessageKeys.IMAGE.DATA] = converted[MessageKeys.IMAGE.DATA]
                    parent[key][MessageKeys.IMAGE.WIDTH] = converted[MessageKeys.IMAGE.WIDTH]
                    parent[key][MessageKeys.IMAGE.HEIGHT] = converted[MessageKeys.IMAGE.HEIGHT]
                else:
                    parent[key] = converted
                    
            elif mode == 'to_numpy':
                # Convert to numpy
                numpy_array = self._base64_to_numpy(data)
                
                # Update the target dict in place if it exists
                if key in parent and isinstance(parent[key], dict):
                    parent[key][MessageKeys.IMAGE.FORMAT] = 'bgr'
                    parent[key][MessageKeys.IMAGE.ENCODING] = 'numpy'
                    parent[key][MessageKeys.IMAGE.DATA] = numpy_array
                    parent[key][MessageKeys.IMAGE.WIDTH] = numpy_array.shape[1]
                    parent[key][MessageKeys.IMAGE.HEIGHT] = numpy_array.shape[0]
                else:
                    parent[key] = {
                        MessageKeys.IMAGE.FORMAT: 'bgr',
                        MessageKeys.IMAGE.ENCODING: 'numpy',
                        MessageKeys.IMAGE.DATA: numpy_array,
                        MessageKeys.IMAGE.WIDTH: numpy_array.shape[1],
                        MessageKeys.IMAGE.HEIGHT: numpy_array.shape[0]
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
        
        img_format = self.config.get(MessageKeys.IMAGE.FORMAT, 'jpeg')
        
        if img_format == 'jpeg':
            quality = self.get_config_int(MessageKeys.IMAGE.JPEG_QUALITY, 85)
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
            MessageKeys.IMAGE.FORMAT: ext,
            MessageKeys.IMAGE.ENCODING: 'base64',
            MessageKeys.IMAGE.DATA: img_base64,
            MessageKeys.IMAGE.WIDTH: image.shape[1],
            MessageKeys.IMAGE.HEIGHT: image.shape[0]
        }
    
    def _base64_to_numpy(self, data: Any) -> np.ndarray:
        """Convert base64 encoded image to numpy array."""
        # Handle dict format
        if isinstance(data, dict):
            img_data = data.get(MessageKeys.IMAGE.DATA)
            if img_data is None:
                raise ValueError(f"No '{MessageKeys.IMAGE.DATA}' field in image dict")
        # Handle raw base64 string
        elif isinstance(data, str):
            img_data = data
            # Remove data URL prefix if present
            if img_data.startswith(f'{MessageKeys.IMAGE.DATA}:{MessageKeys.IMAGE.PATH}'):
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
