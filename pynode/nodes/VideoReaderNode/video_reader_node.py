"""
Video Reader node - plays a video file frame-by-frame with transport
controls (play/pause, stop, step) rendered on the node itself.
"""

import base64
import os
import threading
import time
from typing import Any, Dict, Optional

import cv2

from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Reads a video file and outputs its frames as JPEG (base64) "
               "messages. Playback is driven by the transport controls on the "
               "node: play/pause, stop, and single-frame stepping.")
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Frame message (payload.image JPEG base64) with frame index, "
                  "total frame count and source path."),
)
_info.add_header("Transport Controls")
_info.add_bullets(
    ("⏮ Step back:", "Show the previous frame (while paused/stopped)."),
    ("⏯ Play/Pause:", "Toggle playback from the current position."),
    ("⏹ Stop:", "Halt playback and seek back to the first frame."),
    ("⏭ Step forward:", "Show the next frame (while paused/stopped)."),
)
_info.add_header("Properties")
_info.add_bullets(
    ("Video File:", "Upload a video or enter a path manually."),
    ("Frame Rate:", "Playback FPS override; 0 uses the video's native rate."),
    ("Loop:", "Restart from the first frame when the video ends."),
    ("JPEG Quality:", "Encoding quality for the emitted frames (1-100)."),
)
_info.add_header("Output Format")
_info.add_bullets(
    (f"{MessageKeys.PAYLOAD}.image:", "JPEG base64 image dict (format/encoding/data/width/height)."),
    (f"{MessageKeys.PAYLOAD}.frame:", "Zero-based index of the emitted frame."),
    (f"{MessageKeys.PAYLOAD}.total_frames:", "Total number of frames in the video."),
    (f"{MessageKeys.PAYLOAD}.source:", "Path of the video file."),
)


class VideoReaderNode(BaseNode):
    """
    Video Reader node - serves frames from an uploaded video file with
    play/pause/stop/step transport controls.

    The playback worker thread is only started when the user presses play
    (NOT in on_start); all VideoCapture access (seek + read from the playback
    thread and from the step/stop actions) is guarded by a lock.
    """
    info = str(_info)
    display_name = 'Video Reader'
    icon = '🎞️'
    category = 'input'
    color = '#C0DEED'
    border_color = '#7FA7C9'
    text_color = '#000000'
    input_count = 0
    output_count = 1

    # Transport controls rendered on the node (see 'transport-controls' in
    # static/js/nodes.js); each button POSTs its action to
    # /api/nodes/<id>/<action>.
    ui_component = 'transport-controls'
    ui_component_config = {
        'buttons': [
            {'icon': '⏮', 'action': 'step_prev', 'title': 'Step back one frame'},
            {'icon': '⏯', 'action': 'play_pause', 'title': 'Play / Pause'},
            {'icon': '⏹', 'action': 'stop', 'title': 'Stop (back to first frame)'},
            {'icon': '⏭', 'action': 'step_next', 'title': 'Step forward one frame'},
        ],
    }

    # UI-triggerable actions (see BaseNode.actions)
    actions = ['play_pause', 'stop', 'step_prev', 'step_next']

    # get_position_sse does its own change-detection (returns None when the
    # position/playing state is unchanged), so the throttle just bounds the
    # comparison rate.
    sse_handlers = [
        {'type': 'video_position', 'handler': 'get_position_sse', 'throttle': 0.2},
    ]

    api_routes = [
        {
            'route': 'upload_video',
            'methods': ['POST'],
            'handler': 'handle_upload_video',
            'type': 'file_upload',
            'allowed_extensions': {'.mp4', '.avi', '.mov', '.mkv', '.webm'},
        },
    ]

    DEFAULT_CONFIG = {
        MessageKeys.VIDEO.SOURCE: '',
        MessageKeys.CAMERA.FPS: 0,
        MessageKeys.VIDEO.LOOP: False,
        MessageKeys.CAMERA.JPEG_QUALITY: 80,
    }

    properties = [
        {
            'name': MessageKeys.VIDEO.SOURCE,
            'label': 'Video File',
            'type': 'file',
            'accept': '.mp4,.avi,.mov,.mkv,.webm',
            'uploadRoute': 'upload_video',
            'placeholder': 'Upload or enter video file path...',
        },
        {
            'name': MessageKeys.CAMERA.FPS,
            'label': 'Frame Rate (FPS, 0 = native)',
            'type': 'number',
            'default': DEFAULT_CONFIG[MessageKeys.CAMERA.FPS],
            'help': "Playback rate override; 0 uses the video's native FPS",
        },
        {
            'name': MessageKeys.VIDEO.LOOP,
            'label': 'Loop',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG[MessageKeys.VIDEO.LOOP],
        },
        {
            'name': MessageKeys.CAMERA.JPEG_QUALITY,
            'label': 'JPEG Quality (1-100)',
            'type': 'number',
            'default': DEFAULT_CONFIG[MessageKeys.CAMERA.JPEG_QUALITY],
        },
    ]

    def __init__(self, node_id=None, name="video reader"):
        super().__init__(node_id, name)
        # VideoCapture state - every access goes through _cap_lock because
        # the playback thread and the transport actions (stop/step) both
        # seek/read the capture.
        self._cap: Optional[cv2.VideoCapture] = None
        self._cap_lock = threading.RLock()
        self._video_path: Optional[str] = None
        self._total_frames = 0
        self._native_fps = 0.0
        # Index of the NEXT frame to read (the displayed frame is one less).
        self._frame_index = 0
        # Playback thread state; transport actions are serialized by
        # _transport_lock so play/stop/step can't interleave.
        self._playing = False
        self._play_thread: Optional[threading.Thread] = None
        self._transport_lock = threading.Lock()
        # Last position broadcast via SSE (change detection).
        self._last_sse_state = None

    # ------------------------------------------------------------------
    # Upload route
    # ------------------------------------------------------------------

    def handle_upload_video(self, file_bytes, filename):
        """Handle video file upload via the dynamic API route.

        Follows the FrameSourceNode convention: files are saved to a
        'videos' directory next to this node module.
        """
        try:
            videos_dir = os.path.join(os.path.dirname(__file__), 'videos')
            os.makedirs(videos_dir, exist_ok=True)

            file_path = os.path.join(videos_dir, os.path.basename(filename))
            with open(file_path, 'wb') as f:
                f.write(file_bytes)

            return {
                'success': True,
                'file_path': file_path,
                'filename': filename,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self):
        """Start the base worker thread only - playback waits for play."""
        super().on_start()

    def on_stop(self):
        """Halt playback and release the capture when the workflow stops."""
        super().on_stop()
        self._halt_playback()
        with self._cap_lock:
            self._release_capture()

    def on_close(self):
        """Cleanup when node is deleted."""
        self.on_stop()

    # ------------------------------------------------------------------
    # Transport actions (declared in `actions`)
    # ------------------------------------------------------------------

    def play_pause(self):
        """Toggle playback: pause if playing, otherwise play from the
        current position (from the start if at the end and loop is off)."""
        with self._transport_lock:
            if self._playing:
                self._halt_playback()
                return
            if not self._ensure_capture():
                return
            with self._cap_lock:
                # Pressing play at the end restarts from the first frame.
                if self._total_frames and self._frame_index >= self._total_frames:
                    self._frame_index = 0
            self._playing = True
            self._play_thread = threading.Thread(target=self._playback_loop,
                                                 daemon=True)
            self._play_thread.start()

    def stop(self):
        """Halt playback and seek back to the first frame."""
        with self._transport_lock:
            self._halt_playback()
            with self._cap_lock:
                if self._cap is not None and self._cap.isOpened():
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self._frame_index = 0

    def step_next(self):
        """Emit the next frame (only meaningful while paused/stopped)."""
        with self._transport_lock:
            if self._playing:
                return
            if not self._ensure_capture():
                return
            index = self._frame_index
            if self._total_frames and index >= self._total_frames:
                if not self.get_config_bool(MessageKeys.VIDEO.LOOP, False):
                    return  # at the end, no loop -> nothing to step to
                index = 0
            self._emit_frame_at(index)

    def step_prev(self):
        """Emit the previous frame (only meaningful while paused/stopped)."""
        with self._transport_lock:
            if self._playing:
                return
            if not self._ensure_capture():
                return
            displayed = self._frame_index - 1
            target = max(0, displayed - 1)
            self._emit_frame_at(target)

    # ------------------------------------------------------------------
    # SSE position reporting
    # ------------------------------------------------------------------

    def get_position_sse(self):
        """SSE handler: report {frame, total, playing} only on change."""
        frame = max(0, self._frame_index - 1)
        sse_state = (frame, self._total_frames, self._playing)
        if sse_state == self._last_sse_state:
            return None
        self._last_sse_state = sse_state
        return {
            'frame': frame,
            'total': self._total_frames,
            'playing': self._playing,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _release_capture(self):
        """Release the VideoCapture. Caller must hold _cap_lock."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._video_path = None

    def _ensure_capture(self) -> bool:
        """Open (or re-open on path change) the configured video file."""
        path = str(self.config.get(MessageKeys.VIDEO.SOURCE, '') or '').strip()
        if not path:
            self.report_error("No video file configured")
            return False
        with self._cap_lock:
            if (self._cap is not None and self._cap.isOpened()
                    and path == self._video_path):
                return True
            self._release_capture()
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                self.report_error(f"Failed to open video: {path}")
                return False
            self._cap = cap
            self._video_path = path
            self._total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self._native_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            self._frame_index = 0
            return True

    def _halt_playback(self):
        """Stop the playback thread and join it (never joins itself)."""
        self._playing = False
        thread = self._play_thread
        if (thread is not None and thread.is_alive()
                and thread is not threading.current_thread()):
            thread.join(timeout=2.0)
        self._play_thread = None

    def _emit_frame_at(self, index: int) -> bool:
        """Seek to `index` (if needed), read one frame and send it."""
        with self._cap_lock:
            cap = self._cap
            if cap is None or not cap.isOpened():
                return False
            if int(cap.get(cv2.CAP_PROP_POS_FRAMES)) != index:
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ret, frame = cap.read()
            if not ret or frame is None:
                return False
            self._frame_index = index + 1
            total = self._total_frames
            path = self._video_path

        quality = self.get_config_int(MessageKeys.CAMERA.JPEG_QUALITY, 80)
        ok, buffer = cv2.imencode('.jpg', frame,
                                  (cv2.IMWRITE_JPEG_QUALITY, quality))
        if not ok:
            self.report_error("Failed to encode frame as JPEG")
            return False
        jpeg_base64 = base64.b64encode(buffer.tobytes()).decode('utf-8')

        image_payload = {
            MessageKeys.IMAGE.FORMAT: 'jpeg',
            MessageKeys.IMAGE.ENCODING: 'base64',
            MessageKeys.IMAGE.DATA: jpeg_base64,
            MessageKeys.IMAGE.WIDTH: frame.shape[1],
            MessageKeys.IMAGE.HEIGHT: frame.shape[0],
        }
        message_payload: Dict[str, Any] = {
            MessageKeys.IMAGE.PATH: image_payload,
            'frame': index,
            'total_frames': total,
            MessageKeys.VIDEO.SOURCE: path,
        }
        msg = self.create_message(payload=message_payload,
                                  topic='video/frame', frame_count=index)
        self.send(msg)
        return True

    def _playback_loop(self):
        """Worker thread: emit frames paced to the (native or override) FPS."""
        fps = self.get_config_float(MessageKeys.CAMERA.FPS, 0)
        if fps <= 0:
            fps = self._native_fps
        if fps <= 0:
            fps = 30.0
        frame_interval = 1.0 / fps
        loop = self.get_config_bool(MessageKeys.VIDEO.LOOP, False)

        while self._playing:
            start_time = time.time()

            with self._cap_lock:
                if self._cap is None or not self._cap.isOpened():
                    self._playing = False
                    break
                index = self._frame_index
                if self._total_frames and index >= self._total_frames:
                    if loop:
                        index = 0
                    else:
                        # End of video, no loop: stop emitting; position
                        # remains at the last frame.
                        self._playing = False
                        break

            if not self._emit_frame_at(index):
                # Read failure (or end reached without a frame count).
                if loop and self._total_frames:
                    with self._cap_lock:
                        self._frame_index = 0
                    continue
                self._playing = False
                break

            elapsed = time.time() - start_time
            sleep_time = max(0.0, frame_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)
