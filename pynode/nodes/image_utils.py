"""Image decode/encode helpers and the ``process_image`` decorator.

Extracted from ``base_node.py``; ``pynode.nodes.base_node`` re-exports
``process_image`` (and ``BaseNode.decode_image`` / ``BaseNode.encode_image``
remain as thin delegates to :func:`decode_image` / :func:`encode_image`) so
existing imports and call sites keep working.

The module-level functions report failures via an optional ``report_error``
callback (a ``Callable[[str], None]``; nodes pass ``self.report_error``) and
return ``None`` results on error — identical semantics to the original
BaseNode methods.
"""

import base64
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np
import cv2

from pynode.nodes.messages import MessageKeys


def _noop_report_error(error_msg: str) -> None:
    """Default error sink when no report_error callback is supplied."""


def decode_image(payload: Any,
                 report_error: Optional[Callable[[str], None]] = None
                 ) -> Tuple[Any, Optional[str]]:
    """
    Decode image from various formats into a numpy array.
    Returns (image, format_type) tuple where format_type indicates the input format.

    Supported formats:
    - Direct numpy array
    - Dict with 'format', 'encoding', 'data' (camera node format)
    - Direct base64 string

    Args:
        payload: Image payload in any supported format
        report_error: Optional callback invoked with an error message on
            failure (e.g. ``BaseNode.report_error``)

    Returns:
        Tuple of (image as numpy array or None, format_identifier string or None)
    """
    report_error = report_error or _noop_report_error

    try:
        # Handle nested payload.image structure
        if isinstance(payload, dict) and MessageKeys.IMAGE.PATH in payload:
            payload = payload[MessageKeys.IMAGE.PATH]

        # Direct numpy array
        if isinstance(payload, np.ndarray):
            return payload, 'numpy_array'

        # Camera node format: dict with 'format', 'encoding', 'data'
        if isinstance(payload, dict):
            img_format = payload.get('format')
            encoding = payload.get('encoding')
            data = payload.get('data')

            if img_format == 'bgr' and encoding == 'numpy':
                # Direct numpy array in dict
                if isinstance(data, np.ndarray):
                    return data, 'bgr_numpy_dict'
                report_error("Expected numpy array in bgr/numpy dict format")
                return None, None

            elif img_format == 'jpeg' and encoding == 'base64':
                # Base64 JPEG
                img_bytes = base64.b64decode(data) # type: ignore
                nparr = np.frombuffer(img_bytes, np.uint8)
                image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                return image, 'jpeg_base64_dict'

            elif img_format == 'bgr' and encoding == 'raw':
                # Raw list format
                image = np.array(data, dtype=np.uint8)
                return image, 'bgr_raw_dict'

            report_error(f"Unknown image dict format: {img_format}/{encoding}")
            return None, None

        # Direct base64 string
        if isinstance(payload, str):
            # Remove data URL prefix if present
            if payload.startswith('data:image'):
                payload = payload.split(',')[1]

            img_bytes = base64.b64decode(payload)
            nparr = np.frombuffer(img_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            return image, 'base64_string'

        report_error(f"Unsupported image payload type: {type(payload).__name__}")
        return None, None

    except Exception as e:
        report_error(f"Failed to decode image: {e}")
        return None, None


def encode_image(image: Any, format_type: Optional[str],
                 report_error: Optional[Callable[[str], None]] = None) -> Any:
    """
    Encode numpy array image back to the original format.

    Args:
        image: Numpy array image
        format_type: Format identifier from decode_image()
        report_error: Optional callback invoked with an error message on
            failure (e.g. ``BaseNode.report_error``)

    Returns:
        Encoded image in the specified format, or None on error
    """
    report_error = report_error or _noop_report_error

    try:
        if not isinstance(image, np.ndarray):
            report_error("Cannot encode: input is not a numpy array")
            return None

        if format_type == 'numpy_array':
            # Direct numpy array
            return image

        elif format_type == 'bgr_numpy_dict':
            # Dict with numpy array
            return {
                'format': 'bgr',
                'encoding': 'numpy',
                'data': image,
                'width': image.shape[1],
                'height': image.shape[0]
            }

        elif format_type == 'jpeg_base64_dict':
            # JPEG base64 dict
            ret, buffer = cv2.imencode('.jpg', image)
            if ret:
                jpeg_base64 = base64.b64encode(buffer.tobytes()).decode('utf-8')
                return {
                    'format': 'jpeg',
                    'encoding': 'base64',
                    'data': jpeg_base64,
                    'width': image.shape[1],
                    'height': image.shape[0]
                }
            report_error("Failed to encode image as JPEG base64 dict")
            return None

        elif format_type == 'bgr_raw_dict':
            # Raw list dict
            return {
                'format': 'bgr',
                'encoding': 'raw',
                'data': image.tolist(),
                'width': image.shape[1],
                'height': image.shape[0]
            }

        elif format_type == 'base64_string':
            # Direct base64 string
            ret, buffer = cv2.imencode('.jpg', image)
            if ret:
                return base64.b64encode(buffer.tobytes()).decode('utf-8')
            report_error("Failed to encode image as base64 string")
            return None

        report_error(f"Unknown image format type: {format_type}")
        return None

    except Exception as e:
        report_error(f"Failed to encode image: {e}")
        return None


def process_image(payload_path: str = MessageKeys.PAYLOAD, output_path: Optional[str] = None):
    """
    Decorator for image processing node methods.
    Automatically handles image decoding/encoding and error handling.

    This decorator:
    1. Extracts the image from msg using payload_path
    2. Decodes it to a numpy array
    3. Calls the decorated function with (self, image, msg, input_index)
    4. Encodes the result back to original format
    5. Places result at output_path (or payload_path.image if not specified)
    6. Sends the message

    The decorated function should return:
    - numpy array: The processed image
    - tuple (numpy array, dict): Image and additional msg fields to merge
    - None: Skip sending (function handles send itself)

    Args:
        payload_path: Dot-notation path to image in msg (default: 'payload')
        output_path: Dot-notation path for output image (default: payload_path + '.image' or 'payload.image')

    Example:
        @process_image(payload_path='payload')
        def process(self, image, msg, input_index):
            # image is already decoded as numpy array
            result = cv2.GaussianBlur(image, (5, 5), 0)
            return result  # Will be auto-encoded and sent

        @process_image(payload_path='payload')
        def process(self, image, msg, input_index):
            result = cv2.GaussianBlur(image, (5, 5), 0)
            return result, {'blur_applied': True}  # Adds extra field to msg
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, msg: Dict[str, Any], input_index: int = 0):
            # Check for payload
            if MessageKeys.PAYLOAD not in msg:
                self.send(msg)
                return

            # Get the image data from the specified path
            image_data = msg
            path_parts = payload_path.split('.')
            for part in path_parts:
                if isinstance(image_data, dict) and part in image_data:
                    image_data = image_data[part]
                else:
                    # Path not found, pass through
                    self.send(msg)
                    return

            # Decode image (self.decode_image so node overrides still apply)
            image, format_type = self.decode_image(image_data)
            if image is None:
                self.send(msg)
                return

            # Call the processing function
            try:
                result = func(self, image, msg, input_index)
            except Exception as e:
                self.report_error(f"Image processing error: {e}")
                return

            # Handle different return types
            if result is None:
                # Function handled send itself
                return

            extra_fields: Dict[str, Any] = {}
            result_image: np.ndarray | None = None  # Explicit type hint

            if isinstance(result, tuple):
                result_image, extra_fields = result
            else:
                result_image = result

            # Encode and place in output path
            if result_image is not None and isinstance(result_image, np.ndarray):
                encoded = self.encode_image(result_image, format_type)

                # Determine output path
                out_path = output_path
                if out_path is None:
                    # Default: if payload_path is 'payload', use 'payload.image'
                    # Otherwise use payload_path + '.image'
                    if payload_path == MessageKeys.PAYLOAD:
                        out_path = f"{MessageKeys.PAYLOAD}.{MessageKeys.IMAGE.PATH}"
                    else:
                        out_path = payload_path

                # Navigate to output location and set value
                out_parts = out_path.split('.')
                target = msg
                for part in out_parts[:-1]:
                    if part not in target or not isinstance(target[part], dict):
                        target[part] = {}
                    target = target[part]
                target[out_parts[-1]] = encoded

            # Merge extra fields into msg
            if extra_fields:
                msg.update(extra_fields)

            self.send(msg)

        return wrapper
    return decorator
