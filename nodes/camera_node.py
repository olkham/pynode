"""
Camera node - captures frames from a webcam using OpenCV.
"""

import cv2
import base64
import threading
import time
from typing import Any, Dict
from base_node import BaseNode


class CameraNode(BaseNode):
    """
    Camera node - captures frames from a webcam and outputs them as messages.
    """
    display_name = 'Camera'
    icon = '📷'
    category = 'input'
    color = '#C0DEED'
    border_color = '#7FA7C9'
    text_color = '#000000'
    input_count = 0  # No input
    output_count = 1
    
    properties = [
        {
            'name': 'camera_index',
            'label': 'Camera Index',
            'type': 'number',
            'default': 0
        },
        {
            'name': 'fps',
            'label': 'Frame Rate (FPS)',
            'type': 'number',
            'default': 10
        },
        {
            'name': 'width',
            'label': 'Width',
            'type': 'number',
            'default': 640
        },
        {
            'name': 'height',
            'label': 'Height',
            'type': 'number',
            'default': 480
        },
        {
            'name': 'encode_jpeg',
            'label': 'Encode as JPEG',
            'type': 'checkbox',
            'default': True
        }
    ]
    
    def __init__(self, node_id=None, name="camera"):
        super().__init__(node_id, name)
        self.camera = None
        self.capture_thread = None
        self.running = False
        self.configure({
            'camera_index': 0,
            'fps': 10,
            'width': 640,
            'height': 480,
            'encode_jpeg': True
        })
    
    def on_start(self):
        """Start the camera capture when workflow starts."""
        camera_index = int(self.config.get('camera_index', 0))
        fps = int(self.config.get('fps', 10))
        width = int(self.config.get('width', 640))
        height = int(self.config.get('height', 480))
        
        try:
            # Open the camera
            self.camera = cv2.VideoCapture(camera_index)
            
            if not self.camera.isOpened():
                print(f"[Camera {self.id}] Failed to open camera {camera_index}")
                return
            
            # Set resolution
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            
            print(f"[Camera {self.id}] Opened camera {camera_index} at {width}x{height}")
            
            # Start capture thread
            self.running = True
            self.capture_thread = threading.Thread(target=self._capture_loop, args=(fps,), daemon=True)
            self.capture_thread.start()
            
        except Exception as e:
            print(f"[Camera {self.id}] Error starting camera: {e}")
    
    def on_stop(self):
        """Stop the camera capture when workflow stops."""
        self.running = False
        
        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)
            self.capture_thread = None
        
        if self.camera:
            self.camera.release()
            self.camera = None
            print(f"[Camera {self.id}] Camera released")
    
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
                    print(f"[Camera {self.id}] Failed to capture frame")
                    time.sleep(frame_interval)
                    continue
                
                # Prepare the payload
                if encode_jpeg:
                    # Encode frame as JPEG
                    ret, buffer = cv2.imencode('.jpg', frame)
                    if ret:
                        # Convert to base64 for easy transmission
                        jpeg_base64 = base64.b64encode(buffer).decode('utf-8')
                        payload = {
                            'format': 'jpeg',
                            'encoding': 'base64',
                            'data': jpeg_base64,
                            'width': frame.shape[1],
                            'height': frame.shape[0]
                        }
                    else:
                        print(f"[Camera {self.id}] Failed to encode JPEG")
                        continue
                else:
                    # Send raw frame data
                    payload = {
                        'format': 'bgr',
                        'encoding': 'raw',
                        'data': frame.tolist(),
                        'width': frame.shape[1],
                        'height': frame.shape[0]
                    }
                
                # Create and send message
                msg = self.create_message(payload=payload, topic='camera/frame')
                self.send(msg)
                
            except Exception as e:
                print(f"[Camera {self.id}] Error capturing frame: {e}")
            
            # Maintain frame rate
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
