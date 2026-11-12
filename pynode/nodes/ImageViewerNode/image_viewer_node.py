"""
Image Viewer node - displays images/frames in the web UI.
"""

import base64
import threading
import time
from typing import Any

import cv2

from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Displays images and video frames directly in the web UI. Automatically converts incoming image data to a displayable format.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with image data at the configured image path.")
)
_info.add_header("Supported Formats")
_info.add_bullets(
    ("Numpy Array:", "OpenCV BGR image arrays."),
    ("Base64:", "Base64 encoded JPEG/PNG strings."),
    ("Dict:", "Image dict with 'data' and 'encoding' keys.")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Width/Height:", "Display size in pixels (image is scaled to fit)."),
    ("Image Path:", f"Dot-separated path to image data (e.g., {MessageKeys.PAYLOAD}.{MessageKeys.IMAGE.PATH}).")
)


class ImageViewerNode(BaseNode):
    """
    Image Viewer node - displays images/frames in the web UI.
    """
    display_name = 'Image Viewer'
    icon = '🖼️'
    category = 'output'
    color = '#D8BFD8'
    border_color = '#9370DB'
    text_color = '#000000'
    input_count = 1
    output_count = 0
    info = str(_info)
    
    api_routes = [
        {'route': 'frame', 'methods': ['GET'], 'handler': 'get_current_frame'},
        {'route': 'stream', 'methods': ['GET'], 'handler': 'get_mjpeg_stream', 'type': 'stream'},
    ]
    
    sse_handlers = [
        {'type': 'frame', 'handler': 'get_current_frame_sse'},
    ]
    
    DEFAULT_CONFIG = {
        MessageKeys.IMAGE.WIDTH: 320,
        MessageKeys.IMAGE.HEIGHT: 240,
        'image_path': f'{MessageKeys.PAYLOAD}.{MessageKeys.IMAGE.PATH}'
    }
    
    properties = [
        {
            'name': MessageKeys.IMAGE.WIDTH,
            'label': 'Display Width (px)',
            'type': 'number',
            'default': DEFAULT_CONFIG[MessageKeys.IMAGE.WIDTH]
        },
        {
            'name': MessageKeys.IMAGE.HEIGHT,
            'label': 'Display Height (px)',
            'type': 'number',
            'default': DEFAULT_CONFIG[MessageKeys.IMAGE.HEIGHT]
        },
        {
            'name': 'image_path',
            'label': 'Image Data Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['image_path'],
            'description': f'Dot-separated path to image data (e.g. {MessageKeys.PAYLOAD}.{MessageKeys.IMAGE.PATH})'
        },
        {
            'name': 'stream_url',
            'label': 'Stream URL',
            'type': 'streamUrl',
            'help': 'MJPEG stream URL - open in browser or use in other applications'
        }
    ]
    
    # Only reads the incoming frame (it is never modified or forwarded), so
    # senders can hand it over without a deepcopy.
    shares_input = True

    # The editor card never needs more than this many frames per second; the
    # MJPEG stream route is not limited by it.
    UI_MAX_FPS = 30.0
    # JPEG quality for the editor preview and the MJPEG stream.
    JPEG_QUALITY = 80

    def __init__(self, node_id=None, name="image viewer"):
        super().__init__(node_id, name)
        # Latest frame as received (numpy array, or an already-encoded image
        # dict / string) and when it arrived. Encoding is done lazily, by
        # whoever asks for the frame, and cached per frame - see
        # _encoded_frame(). `current_frame` stays truthy-when-present for
        # callers that only check for a frame.
        self.current_frame = None
        self.frame_timestamp = 0
        # Frames are told apart by a counter, not by frame_timestamp: the
        # wall clock only ticks every ~15 ms on Windows, so two frames of a
        # fast source can carry the same timestamp.
        self._frame_seq = 0
        self.last_sent_timestamp = 0  # dedupe state (frame seq) for the polled GET 'frame' route
        self._sse_last_sent = 0  # dedupe state (frame seq) for the SSE 'frame' broadcaster
        self._sse_next_due = 0.0  # monotonic time the next SSE frame may go out (rate cap)
        self._encode_lock = threading.Lock()
        # (frame seq, preview: bool) -> encoded result, for the newest frame only
        self._encode_cache: dict[tuple, Any] = {}

    def on_input(self, msg: dict[str, Any], input_index: int = 0):
        """
        Receive image data and keep it for display.

        Runs on the SENDER's thread (direct sink), once per message, so it
        must stay trivial: it only stores a reference. JPEG-encoding a full
        frame here used to cost the upstream node ~15 ms per 1080p frame -
        more than the whole frame budget of a 60 fps source - even though the
        browser shows a small preview at a fraction of that rate.
        """
        image_path = self.config.get('image_path', MessageKeys.PAYLOAD)
        image_data = self._get_nested_value(msg, image_path)

        if image_data is None:
            self.report_error(f"ImageViewerNode: No data found at path '{image_path}' in message.")
            return

        self.current_frame = image_data
        self.frame_timestamp = time.time()
        self._frame_seq += 1

    def on_input_direct(self, msg: dict[str, Any], input_index: int = 0):
        """
        Direct input processing (bypasses queue for better performance).
        """
        self.on_input(msg, input_index)

    # ------------------------------------------------------------------
    # Lazy encoding
    # ------------------------------------------------------------------

    def _preview_limit(self) -> tuple[int, int]:
        """Largest (width, height) worth sending to the editor card.

        Twice the configured display size (sharp on HiDPI screens and when
        the canvas is zoomed in), with a floor so small cards stay legible.
        """
        try:
            width = int(float(self.config.get(MessageKeys.IMAGE.WIDTH, 320)))
            height = int(float(self.config.get(MessageKeys.IMAGE.HEIGHT, 240)))
        except (TypeError, ValueError):
            width, height = 320, 240
        return max(width * 2, 640), max(height * 2, 480)

    def _encode(self, raw: Any, preview: bool):
        """Encode one stored frame to the base64-JPEG dict the UI expects."""
        img, _ = self.decode_image({MessageKeys.IMAGE.PATH: raw})
        if img is None:
            self.report_error("ImageViewerNode: Failed to decode image")
            return None

        if preview:
            max_w, max_h = self._preview_limit()
            height, width = img.shape[:2]
            scale = min(max_w / width, max_h / height)
            if scale < 1.0:
                img = cv2.resize(
                    img, (max(1, int(width * scale)), max(1, int(height * scale))),
                    interpolation=cv2.INTER_AREA)

        ok, buffer = cv2.imencode('.jpg', img, (cv2.IMWRITE_JPEG_QUALITY, self.JPEG_QUALITY))
        if not ok:
            self.report_error("ImageViewerNode: Failed to encode image for display")
            return None
        return {
            'format': 'jpeg',
            'encoding': 'base64',
            'data': base64.b64encode(buffer.tobytes()).decode('ascii'),
            'width': int(img.shape[1]),
            'height': int(img.shape[0]),
        }

    def _encoded_frame(self, preview: bool):
        """Return ``(encoded, frame_seq)`` for the newest frame, encoding once.

        Args:
            preview: True for the editor card (downscaled to the display
                size), False for full resolution (MJPEG stream).
        """
        # Read the counter first: if a new frame lands in between, the result
        # is filed under the older number and simply gets re-encoded next time.
        timestamp, raw = self._frame_seq, self.current_frame
        if raw is None:
            return None, timestamp

        key = (timestamp, preview)
        with self._encode_lock:
            cached = self._encode_cache.get(key)
            if cached is None:
                cached = self._encode(raw, preview)
                # Keep results for the newest frame only.
                self._encode_cache = {
                    k: v for k, v in self._encode_cache.items() if k[0] == timestamp}
                if cached is not None:
                    self._encode_cache[key] = cached
        return cached, timestamp

    def get_current_frame(self):
        """
        Get the current frame for display in the UI via the polled GET 'frame' route.
        Only returns frames that haven't been sent yet via this route. Tracks its
        own dedupe state (last_sent_timestamp) so it doesn't steal frames from the
        SSE broadcaster (get_current_frame_sse), which polls independently.
        """
        if self.current_frame is None or self._frame_seq <= self.last_sent_timestamp:
            return None
        encoded, timestamp = self._encoded_frame(preview=True)
        if encoded is None:
            return None
        self.last_sent_timestamp = timestamp
        return encoded

    def get_current_frame_sse(self):
        """SSE handler: return frame wrapped in 'data' key for client compatibility.
        Tracks its own dedupe state (_sse_last_sent) so it doesn't steal frames
        from the polled GET 'frame' route (get_current_frame).

        Capped at UI_MAX_FPS: a preview card gains nothing from more, and
        every extra frame is encoded here and decoded again by the browser."""
        if self.current_frame is None or self._frame_seq <= self._sse_last_sent:
            return None
        now = time.monotonic()
        if now < self._sse_next_due:
            return None
        encoded, timestamp = self._encoded_frame(preview=True)
        if encoded is None:
            return None
        self._sse_last_sent = timestamp
        # Schedule from the previous due time, not from "now": the caller
        # polls on its own coarse cadence, and measuring from "now" would
        # round every interval up and land well below the cap.
        self._sse_next_due = max(self._sse_next_due + 1.0 / self.UI_MAX_FPS, now)
        return {'data': encoded}

    def get_mjpeg_stream(self):
        """Generator for MJPEG streaming. Yields JPEG bytes at full resolution.
        Exits once the node is stopped so the stream doesn't keep a server
        thread alive forever."""
        last_timestamp = 0
        while not self._stop_worker_flag:
            try:
                if self._frame_seq > last_timestamp and self.current_frame is not None:
                    frame_data, timestamp = self._encoded_frame(preview=False)
                    last_timestamp = timestamp
                    if isinstance(frame_data, dict) and 'data' in frame_data:
                        yield base64.b64decode(frame_data['data'])
                    else:
                        time.sleep(0.033)
                else:
                    time.sleep(0.005)
            except Exception:
                time.sleep(0.1)
