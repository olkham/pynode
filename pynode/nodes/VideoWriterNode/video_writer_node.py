"""
Video Writer Node - Writes video files from incoming image frames
"""

import os
import time
import cv2
import numpy as np
from datetime import datetime
from pynode.nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Records video files from incoming image frames. Automatically starts recording when frames arrive and supports automatic file rollover based on clip length.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with image data at payload.image")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Recording status events (recording_start, recording_end)")
)
_info.add_header("Supported Codecs")
_info.add_bullets(
    ("MPEG-4:", ".mp4 - Good compatibility, moderate compression"),
    ("H.264/AVC:", ".mp4 - Best compression, wide support"),
    ("Motion JPEG:", ".avi - Each frame is a JPEG, large files"),
    ("Xvid:", ".avi - Good compression, legacy format"),
    ("DivX:", ".avi - Similar to Xvid"),
    ("WMV:", ".wmv - Windows Media format")
)
_info.add_header("Naming Modes")
_info.add_bullets(
    ("Counter:", "Sequential numbering (video_0001.mp4, video_0002.mp4, ...)"),
    ("Timestamp:", "Unix timestamp (video_1767375877.mp4)"),
    ("DateTime:", "Date/time format (video_20260102_174437.mp4)"),
    ("Message:", "From msg.filename field")
)
_info.add_header("Resize Methods")
_info.add_bullets(
    ("Fit:", "Scales to fit within resolution, adds letterbox bars"),
    ("Fill:", "Scales to fill resolution, crops edges"),
    ("Stretch:", "Stretches to exact resolution, ignores aspect ratio")
)
_info.add_header("Output Events")
_info.add_text("When recording starts:")
_info.add_code('{ "event": "recording_start", "filename": "...", "width": 1920, "height": 1080, "framerate": 30, "codec": "mp4v" }')
_info.add_text("When recording ends:")
_info.add_code('{ "event": "recording_end", "filename": "...", "frames": 900 }')


class VideoWriterNode(BaseNode):
    """Writes video files from incoming image frames with various output options"""
    
    display_name = "Video Writer"
    category = "output"
    icon = "🎥"
    color = "#87A980"
    border_color = '#5F7858'
    text_color = '#000000'
    input_count = 1
    output_count = 1  # Output for recording start/end events
    info = str(_info)
    
    DEFAULT_CONFIG = {
        'path': './output',
        'filename': 'video_{counter}',
        'codec': 'mp4v',
        'framerate': 30.0,
        'width': 1920,
        'height': 1080,
        'clip_length': 0,  # 0 = unlimited
        'naming_mode': 'counter',
        'counter_digits': 4,
        'resize_method': 'fit',
        'auto_resolution': False,
    }
    
    # Available codecs with their file extensions
    CODECS = {
        'mp4v': {'fourcc': 'mp4v', 'ext': '.mp4', 'name': 'MPEG-4'},
        'avc1': {'fourcc': 'avc1', 'ext': '.mp4', 'name': 'H.264 (AVC)'},
        'xvid': {'fourcc': 'XVID', 'ext': '.avi', 'name': 'Xvid'},
        'mjpg': {'fourcc': 'MJPG', 'ext': '.avi', 'name': 'Motion JPEG'},
        'divx': {'fourcc': 'DIVX', 'ext': '.avi', 'name': 'DivX'},
        'wmv1': {'fourcc': 'WMV1', 'ext': '.wmv', 'name': 'WMV'},
    }
    
    properties = [
        {
            'name': 'path',
            'label': 'Output Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['path'],
            'placeholder': DEFAULT_CONFIG['path']
        },
        {
            'name': 'filename',
            'label': 'Filename',
            'type': 'text',
            'default': DEFAULT_CONFIG['filename'],
            'placeholder': DEFAULT_CONFIG['filename']
        },
        {
            'name': 'naming_mode',
            'label': 'Naming Mode',
            'type': 'select',
            'options': [
                {'value': 'counter', 'label': 'Counter (0001, 0002, ...)'},
                {'value': 'timestamp', 'label': 'Unix Timestamp'},
                {'value': 'datetime', 'label': 'Date/Time (YYYYMMDD_HHMMSS)'},
                {'value': 'message', 'label': 'From msg.filename'}
            ],
            'default': DEFAULT_CONFIG['naming_mode']
        },
        {
            'name': 'counter_digits',
            'label': 'Counter Digits',
            'type': 'number',
            'default': DEFAULT_CONFIG['counter_digits'],
            'min': 1,
            'max': 10
        },
        {
            'name': 'codec',
            'label': 'Codec',
            'type': 'select',
            'options': [
                {'value': 'mp4v', 'label': 'MPEG-4 (.mp4)'},
                {'value': 'avc1', 'label': 'H.264/AVC (.mp4)'},
                {'value': 'xvid', 'label': 'Xvid (.avi)'},
                {'value': 'mjpg', 'label': 'Motion JPEG (.avi)'},
                {'value': 'divx', 'label': 'DivX (.avi)'},
                {'value': 'wmv1', 'label': 'WMV (.wmv)'},
            ],
            'default': DEFAULT_CONFIG['codec']
        },
        {
            'name': 'framerate',
            'label': 'Frame Rate (FPS)',
            'type': 'number',
            'default': DEFAULT_CONFIG['framerate'],
            'min': 1,
            'max': 120,
            'step': 0.1
        },
        {
            'name': 'auto_resolution',
            'label': 'Auto Resolution',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['auto_resolution']
        },
        {
            'name': 'width',
            'label': 'Width',
            'type': 'number',
            'default': DEFAULT_CONFIG['width'],
            'min': 1,
            'max': 7680
        },
        {
            'name': 'height',
            'label': 'Height',
            'type': 'number',
            'default': DEFAULT_CONFIG['height'],
            'min': 1,
            'max': 4320
        },
        {
            'name': 'resize_method',
            'label': 'Resize Method',
            'type': 'select',
            'options': [
                {'value': 'fit', 'label': 'Fit (preserve aspect, letterbox)'},
                {'value': 'fill', 'label': 'Fill (preserve aspect, crop)'},
                {'value': 'stretch', 'label': 'Stretch (ignore aspect)'}
            ],
            'default': DEFAULT_CONFIG['resize_method']
        },
        {
            'name': 'clip_length',
            'label': 'Clip Length (frames)',
            'type': 'number',
            'default': DEFAULT_CONFIG['clip_length'],
            'min': 0,
            'placeholder': '0 = unlimited'
        },
    ]
    
    def __init__(self, node_id=None, name="video_writer"):
        super().__init__(node_id, name)
        self._writer = None
        self._current_file = None
        self._frame_count = 0
        self._file_counter = 0
        self._recording = False
        self._actual_width = None
        self._actual_height = None
        
    def _generate_filename(self):
        """Generate filename based on naming mode"""
        naming_mode = self.config.get('naming_mode', 'counter')
        filename = self.config.get('filename', 'video_{counter}')
        counter_digits = self.config.get('counter_digits', 4)
        
        if naming_mode == 'counter':
            self._file_counter += 1
            counter_str = str(self._file_counter).zfill(counter_digits)
            filename = filename.replace('{counter}', counter_str)
        elif naming_mode == 'timestamp':
            timestamp = str(int(time.time()))
            filename = filename.replace('{timestamp}', timestamp)
            filename = filename.replace('{counter}', timestamp)
        elif naming_mode == 'datetime':
            dt_str = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = filename.replace('{datetime}', dt_str)
            filename = filename.replace('{counter}', dt_str)
        # 'message' mode is handled in process() with msg.filename
        
        return filename
        
    def _get_file_extension(self):
        """Get the appropriate file extension for the selected codec"""
        codec = self.config.get('codec', 'mp4v')
        return self.CODECS.get(codec, self.CODECS['mp4v'])['ext']
        
    def _resize_frame(self, frame, target_width, target_height):
        """Resize frame according to the configured resize method"""
        h, w = frame.shape[:2]
        resize_method = self.config.get('resize_method', 'fit')
        
        if w == target_width and h == target_height:
            return frame
            
        if resize_method == 'stretch':
            return cv2.resize(frame, (target_width, target_height))
            
        elif resize_method == 'fit':
            # Calculate scale to fit within target while preserving aspect ratio
            scale = min(target_width / w, target_height / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            
            resized = cv2.resize(frame, (new_w, new_h))
            
            # Create canvas and center the resized image (letterbox)
            canvas = np.zeros((target_height, target_width, 3), dtype=np.uint8)
            x_offset = (target_width - new_w) // 2
            y_offset = (target_height - new_h) // 2
            canvas[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
            
            return canvas
            
        elif resize_method == 'fill':
            # Calculate scale to fill target while preserving aspect ratio (will crop)
            scale = max(target_width / w, target_height / h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            
            resized = cv2.resize(frame, (new_w, new_h))
            
            # Crop center to target size
            x_offset = (new_w - target_width) // 2
            y_offset = (new_h - target_height) // 2
            
            return resized[y_offset:y_offset+target_height, x_offset:x_offset+target_width]
            
        return frame
        
    def _start_recording(self, frame, msg=None):
        """Start a new video recording"""
        # Determine output resolution
        auto_resolution = self.config.get('auto_resolution', False)
        
        if auto_resolution:
            self._actual_height, self._actual_width = frame.shape[:2]
        else:
            self._actual_width = self.config.get('width', 1920)
            self._actual_height = self.config.get('height', 1080)
            
        # Generate filename
        naming_mode = self.config.get('naming_mode', 'counter')
        if naming_mode == 'message' and msg and 'filename' in msg:
            filename = msg['filename']
        else:
            filename = self._generate_filename()
            
        # Ensure output directory exists
        output_path = self.config.get('path', './output')
        try:
            os.makedirs(output_path, exist_ok=True)
        except Exception as e:
            self.report_error(f"Failed to create output directory {output_path}: {e}")
            return None
        
        # Build full file path
        ext = self._get_file_extension()
        if not filename.endswith(ext):
            filename = filename + ext
        self._current_file = os.path.abspath(os.path.join(output_path, filename))
        
        # Get codec fourcc
        codec = self.config.get('codec', 'mp4v')
        fourcc_str = self.CODECS.get(codec, self.CODECS['mp4v'])['fourcc']
        fourcc = cv2.VideoWriter_fourcc(*fourcc_str) # type: ignore[attr-defined]
        
        # Get framerate
        framerate = float(self.config.get('framerate', 30.0))
        
        # print(f"[VideoWriter] Creating: {self._current_file}, {fourcc_str}, {framerate}fps, {self._actual_width}x{self._actual_height}")
        
        # Create VideoWriter
        self._writer = cv2.VideoWriter(
            self._current_file,
            fourcc,
            framerate,
            (self._actual_width, self._actual_height)
        )
        
        if not self._writer.isOpened():
            self.report_error(f"Failed to create video writer for {self._current_file}")
            self._writer = None
            return None
            
        self._frame_count = 0
        self._recording = True
        
        # print(f"[VideoWriter] Started recording: {self._current_file} ({self._actual_width}x{self._actual_height})")
        
        # Return recording start event message
        return {
            'event': 'recording_start',
            'filename': self._current_file,
            'width': self._actual_width,
            'height': self._actual_height,
            'framerate': framerate,
            'codec': codec
        }
        
    def _stop_recording(self):
        """Stop current recording and return event message"""
        if self._writer is not None:
            self._writer.release()
            self._writer = None
            
        if self._recording:
            self._recording = False
            filename = self._current_file
            frames = self._frame_count
            self._current_file = None
            self._frame_count = 0
            
            # print(f"[VideoWriter] Stopped recording: {filename} ({frames} frames)")
            
            return {
                'event': 'recording_end',
                'filename': filename,
                'frames': frames
            }
        return None
        
    def on_input(self, msg: dict, input_index: int = 0):
        """Process incoming message with image frame - does NOT forward messages"""
        # Get image from payload
        payload = msg.get('payload', {})
        if isinstance(payload, dict):
            image_data = payload.get('image')
        else:
            image_data = payload if isinstance(payload, np.ndarray) else None
            
        if image_data is None:
            return
        
        # Decode image using base node helper (handles dict format, base64, numpy, etc.)
        image, format_type = self.decode_image({'image': image_data})
        
        if image is None:
            self.report_error("Failed to decode image from payload")
            return
            
        # Ensure image is in correct format (BGR for OpenCV VideoWriter)
        if len(image.shape) == 2:
            # Grayscale to BGR
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif len(image.shape) == 3 and image.shape[2] == 4:
            # RGBA to BGR
            image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
        elif len(image.shape) == 3 and image.shape[2] == 3:
            # Already BGR or RGB - assume BGR (OpenCV standard)
            pass
        else:
            self.report_error(f"Unexpected image shape: {image.shape}")
            return
            
        event_msg = None
        
        # Check if we need to start a new recording
        clip_length = self.config.get('clip_length', 0)
        
        if not self._recording:
            event_msg = self._start_recording(image, msg)
            if event_msg:
                # Send start event (status only, no image)
                self.send({
                    '_msgid': msg.get('_msgid'),
                    'payload': event_msg
                })
                
        # Check clip length limit
        if clip_length > 0 and self._frame_count >= clip_length:
            end_event = self._stop_recording()
            if end_event:
                # Send end event (status only, no image)
                self.send({
                    '_msgid': msg.get('_msgid'),
                    'payload': end_event
                })
            # Start new recording
            event_msg = self._start_recording(image, msg)
            if event_msg:
                self.send({
                    '_msgid': msg.get('_msgid'),
                    'payload': event_msg
                })
                
        # Write frame
        if self._writer is not None:
            # Always resize to match the video's resolution
            # (set from first frame if auto_resolution, or from config otherwise)
            image = self._resize_frame(image, self._actual_width, self._actual_height)
                
            self._writer.write(image)
            self._frame_count += 1
        # Note: No return/send of input message - only recording events are sent
        
    def close(self):
        """Clean up when node is removed or flow stops"""
        event = self._stop_recording()
        if event:
            # Try to send final event
            self.send({'payload': event})
        super().close()
