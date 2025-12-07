"""
Camera node - captures frames from a webcam using OpenCV.
"""

import cv2
import base64
import threading
import time
import sys
from pathlib import Path
from typing import Any, Dict
from nodes.base_node import BaseNode

# Add FrameSource package to path
_framesource_path = Path(__file__).parent / 'FrameSource'
if str(_framesource_path) not in sys.path:
    sys.path.insert(0, str(_framesource_path))

from frame_source import FrameSourceFactory


class FrameSourceNode(BaseNode):
    """
    Frame Source node - captures frames from a webcam and outputs them as messages.
    """
    display_name = 'Frame Source'
    icon = '📷'
    category = 'sensors'
    color = '#C0DEED'
    border_color = '#7FA7C9'
    text_color = '#000000'
    input_count = 0  # No input
    output_count = 1

    DEFAULT_CONFIG = {
        'source_type': 'webcam',
        'source': 0,
        'fps': 30,
        'width': 640,
        'height': 480,
        'encode_jpeg': False,
        'jpeg_quality': 75
    }

    properties = [
        {
            'name': 'source_type',
            'label': 'Source Type',
            'type': 'select',
            'options': [
                {'value': 'webcam', 'label': 'Webcam'},
                {'value': 'video_file', 'label': 'Video File'},
                {'value': 'ipcam', 'label': 'RTSP Stream'},
                {'value': 'folder', 'label': 'Image Folder'},
                {'value': 'basler', 'label': 'Basler Camera'},
                {'value': 'realsense', 'label': 'RealSense'},
                {'value': 'screen', 'label': 'Screen Capture'},
                {'value': 'genicam', 'label': 'GenICam Camera'},
                {'value': 'audio_spectrogram', 'label': 'Audio Spectrogram'}
            ],
            'default': DEFAULT_CONFIG['source_type'],
        },
        {
            'name': 'source',
            'label': 'Source',
            'type': 'text',
            'default': str(DEFAULT_CONFIG['source'])
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
        self.frame_count = 0
    
    def on_start(self):
        """Start the camera capture when workflow starts."""
        super().on_start()  # Start base node worker thread
        
        source_type = self.config.get('source_type', 'webcam')
        source = self.config.get('source', 0)
        fps = self.get_config_int('fps', 30)
        width = self.get_config_int('width', 640)
        height = self.get_config_int('height', 480)
        
        try:
            # Create camera with config including resolution and fps
            self.camera = FrameSourceFactory.create(
                source_type, 
                source=source,
                width=width,
                height=height,
                fps=fps
            )
            
            if not self.camera.connect():
                self.report_error(f"Failed to connect to {source_type} source: {source}")
                return
            
            self.frame_count = 0  # Reset frame counter on start
            
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
        encode_jpeg = self.config.get('encode_jpeg', False)
        
        while self.running and self.camera and self.camera.isOpened():
            start_time = time.time()
            
            try:
                ret, frame = self.camera.read()
                
                # Check if frame has 4 channels (RGBD data)
                if ret and frame is not None and len(frame.shape) == 3 and frame.shape[2] == 4:
                    # Split RGB and depth channels
                    rgb_frame = frame[:, :, :3]
                    depth_channel = frame[:, :, 3]
                    frame = rgb_frame
                    has_depth = True
                else:
                    has_depth = False
                    depth_channel = None
                
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
                
                # Create message payload
                message_payload: Dict[str, Any] = {'image': payload}
                
                # Add depth data if available (compatible with RealsenseDepthNode)
                if has_depth:
                    message_payload['depth'] = depth_channel
                
                # Increment frame counter
                self.frame_count += 1
                
                # Create and send message
                msg = self.create_message(payload=message_payload, topic='camera/frame', frame_count=self.frame_count)
                self.send(msg)
                
            except Exception as e:
                self.report_error(f"Error capturing frame: {e}")
            
            # Maintain frame rate
            elapsed = time.time() - start_time
            sleep_time = max(0, frame_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
