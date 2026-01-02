"""
Camera node - captures frames from a webcam using OpenCV.
"""

import cv2
import base64
import threading
import time
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Captures video frames from a webcam or video device using OpenCV and outputs them as messages.")
_info.add_header("Inputs")
_info.add_text("This node has no inputs. It generates frames automatically when the workflow starts.")
_info.add_header("Output")
_info.add_bullets(
    ("payload.image:", "Image data (JPEG base64 or numpy array depending on config)."),
    ("payload.image.width:", "Frame width in pixels."),
    ("payload.image.height:", "Frame height in pixels."),
)
_info.add_header("Properties")
_info.add_bullets(
    ("Camera Index:", "Device index (0 for default camera)."),
    ("Frame Rate:", "Target FPS for capture."),
    ("Width/Height:", "Resolution settings."),
    ("Encode as JPEG:", "Output as base64 JPEG or raw numpy array."),
)


class CameraNode(BaseNode):
    """
    Camera node - captures frames from a webcam and outputs them as messages.
    """
    info = str(_info)
    display_name = 'Camera'
    icon = '📷'
    category = 'sensors'
    color = '#C0DEED'
    border_color = '#7FA7C9'
    text_color = '#000000'
    input_count = 0  # No input
    output_count = 1
    
    DEFAULT_CONFIG = {
        'camera_index': 0,
        'fps': 30,
        'width': 640,
        'height': 480,
        'encode_jpeg': False,
        'jpeg_quality': 75
    }
    
    properties = [
        {
            'name': 'camera_index',
            'label': 'Camera Index',
            'type': 'number',
            'default': DEFAULT_CONFIG['camera_index']
        },
        {
            'name': 'fps',
            'label': 'Frame Rate (FPS)',
            'type': 'number',
            'default': DEFAULT_CONFIG['fps']
        },
        {
            'name': 'width',
            'label': 'Width',
            'type': 'number',
            'default': DEFAULT_CONFIG['width']
        },
        {
            'name': 'height',
            'label': 'Height',
            'type': 'number',
            'default': DEFAULT_CONFIG['height']
        },
        {
            'name': 'encode_jpeg',
            'label': 'Encode as JPEG',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['encode_jpeg']
        },
        {
            'name': 'jpeg_quality',
            'label': 'JPEG Quality (1-100)',
            'type': 'number',
            'default': DEFAULT_CONFIG['jpeg_quality']
        }
    ]
    
    def __init__(self, node_id=None, name="camera"):
        super().__init__(node_id, name)
        self.camera = None
        self.capture_thread = None
        self.running = False
    
    def on_start(self):
        """Start the camera capture when workflow starts."""
        super().on_start()  # Start base node worker thread
        
        camera_index = self.get_config_int('camera_index', 0)
        fps = self.get_config_int('fps', 10)
        width = self.get_config_int('width', 640)
        height = self.get_config_int('height', 480)
        
        try:
            # Open the camera
            self.camera = cv2.VideoCapture(camera_index)
            
            if not self.camera.isOpened():
                self.report_error(f"Failed to open camera {camera_index}")
                return
            
            # Set resolution
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            
            # Start capture thread
            self.running = True
            self.capture_thread = threading.Thread(target=self._capture_loop, args=(fps,), daemon=True)
            self.capture_thread.start()
            
        except Exception as e:
            self.report_error(f"Error starting camera: {e}")
    
    def on_stop(self):
        """Stop the camera capture when workflow stops."""
        super().on_stop()  # Stop base node worker thread
        
        self.running = False
        
        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)
            self.capture_thread = None
        
        if self.camera:
            self.camera.release()
            self.camera = None
    
    def on_close(self):
        """Cleanup when node is deleted."""
        self.on_stop()
    
    def _capture_loop(self, fps):
        """Capture frames in a loop and send them as messages."""
        frame_interval = 1.0 / fps
        encode_jpeg = self.config.get('encode_jpeg', True)
        
        while self.running and self.camera and self.camera.isOpened():
            start_time = time.time()
            
            try:
                ret, frame = self.camera.read()
                
                if not ret or frame is None:
                    self.report_error("Failed to capture frame")
                    time.sleep(frame_interval)
                    continue
                
                # Prepare the payload
                if encode_jpeg:
                    # Encode frame as JPEG with quality setting
                    jpeg_quality = self.get_config_int('jpeg_quality', 75)
                    encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
                    ret, buffer = cv2.imencode('.jpg', frame, encode_params)
                    if ret:
                        # Convert to bytes (more efficient than base64)
                        jpeg_bytes = buffer.tobytes()
                        # Convert to base64 for JSON transmission
                        jpeg_base64 = base64.b64encode(jpeg_bytes).decode('utf-8')
                        payload = {
                            'format': 'jpeg',
                            'encoding': 'base64',
                            'data': jpeg_base64,
                            'width': frame.shape[1],
                            'height': frame.shape[0]
                        }
                    else:
                        self.report_error("Failed to encode JPEG")
                        continue
                else:
                    # Send raw frame as numpy array
                    payload = {
                        'format': 'bgr',
                        'encoding': 'numpy',
                        'data': frame,
                        'width': frame.shape[1],
                        'height': frame.shape[0]
                    }
                
                # Create and send message with image wrapped in payload.image
                msg = self.create_message(payload={'image': payload}, topic='camera/frame')
                self.send(msg)
                
            except Exception as e:
                self.report_error(f"Error capturing frame: {e}")
            
            # Maintain frame rate
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
