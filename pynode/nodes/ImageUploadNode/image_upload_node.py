"""
Image Upload Node - accepts image uploads via drag-and-drop on the node.
Sends the uploaded image downstream as a message.

Optionally re-sends the uploaded image repeatedly at a configured rate, so a
single upload can drive a downstream pipeline continuously while it is being
tuned/adjusted.
"""

import base64
import threading
import time

import numpy as np
import cv2
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Accepts image files via drag-and-drop onto the node. "
               "The uploaded image is sent downstream as a message.")
_info.add_header("Usage")
_info.add_bullets(
    "Drag and drop an image file onto the node in the editor.",
    "Supported formats: JPEG, PNG, BMP, TIFF, WebP.",
)
_info.add_header("Repeat Send")
_info.add_bullets(
    ("Repeat Send:", "When enabled, the uploaded image is re-sent "
                     "continuously at the configured rate - upload once and "
                     "keep a downstream pipeline fed while you adjust it."),
    ("Repeat Rate (fps):", "How many times per second to re-send (e.g. 1 = "
                           "once per second, 20 = 20 fps)."),
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Message with the uploaded image in payload. Emitted once "
                  "on upload, then repeatedly while Repeat Send is on."),
)


class ImageUploadNode(BaseNode):
    """Receives image uploads and sends them downstream, optionally repeating."""

    display_name = 'Image Upload'
    icon = '📤'
    category = 'input'
    color = '#C0DEED'
    border_color = '#87A9C1'
    text_color = '#000000'
    input_count = 0
    output_count = 1
    info = str(_info)

    ui_component = 'image-drop'
    ui_component_config = {
        'tooltip': 'Drop an image here',
    }

    DEFAULT_CONFIG = {
        'repeat_send': False,
        'repeat_rate': 10,
    }

    properties = [
        {
            'name': 'repeat_send',
            'label': 'Repeat Send',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['repeat_send'],
            'help': 'Re-send the uploaded image continuously at the rate below',
        },
        {
            'name': 'repeat_rate',
            'label': 'Repeat Rate (fps)',
            'type': 'number',
            'default': DEFAULT_CONFIG['repeat_rate'],
            'help': 'Sends per second (e.g. 1 = once/sec, 20 = 20 fps)',
        },
    ]

    api_routes = [
        {
            'route': 'upload_image',
            'methods': ['POST'],
            'handler': 'handle_upload_image',
            'type': 'file_upload',
            'allowed_extensions': {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'},
        },
    ]

    def __init__(self, node_id=None, name="image upload"):
        super().__init__(node_id, name)
        # Stored primitives for the most recent upload (immutable pieces:
        # base64 str, ints). A fresh payload dict is rebuilt from these on
        # every send so downstream nodes never share/mutate a common dict.
        self._image_data = None
        # Repeat-send timer.
        self._repeat_thread = None
        self._stop_repeat = threading.Event()
        self._repeat_lock = threading.Lock()

    def _build_message(self):
        """Build a fresh message from the stored image primitives, or None."""
        data = self._image_data  # atomic reference read
        if data is None:
            return None
        return self.create_message(payload={
            'image': {
                'format': 'jpeg',
                'encoding': 'base64',
                'data': data['data'],
                'width': data['width'],
                'height': data['height'],
            },
            'filename': data['filename'],
        })

    def _send_once(self):
        """Send one fresh message for the currently stored image, if any."""
        msg = self._build_message()
        if msg is not None:
            self.send(msg)

    def receive_image(self, image_bytes: bytes, filename: str = ""):
        """
        Called by the server when an image is uploaded to this node.

        Decodes and JPEG-encodes the image, stores it, sends it once
        immediately, and (re)starts the repeat timer if Repeat Send is on.

        Args:
            image_bytes: Raw image file bytes.
            filename: Original filename of the uploaded image.
        """
        # Decode image bytes to numpy array
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is None:
            self.report_error(f"Failed to decode uploaded image: {filename}")
            return

        # Encode as JPEG base64 for the standard image message format
        ret, buffer = cv2.imencode('.jpg', image)
        if not ret:
            self.report_error("Failed to encode uploaded image as JPEG")
            return

        jpeg_base64 = base64.b64encode(buffer.tobytes()).decode('utf-8')

        # Store immutable primitives; replaced wholesale (atomic reference
        # swap), never mutated in place, so the repeat thread can read it
        # concurrently without a lock.
        self._image_data = {
            'data': jpeg_base64,
            'width': image.shape[1],
            'height': image.shape[0],
            'filename': filename,
        }

        # Always send once immediately (preserves the upload-and-send behavior).
        self._send_once()

        # Start repeating if configured (idempotent - won't double-start).
        if self._repeat_enabled():
            self._start_repeat()

    def _repeat_enabled(self):
        """True when Repeat Send is on and the rate is a positive number."""
        return self.get_config_bool('repeat_send', False) and self._repeat_interval() > 0

    def _repeat_interval(self):
        """Seconds between sends from the fps rate; 0 if rate is invalid."""
        fps = self.get_config_float('repeat_rate', 0)
        return 1.0 / fps if fps > 0 else 0.0

    def _start_repeat(self):
        """Start the repeat-send thread if it is not already running."""
        with self._repeat_lock:
            if self._repeat_thread and self._repeat_thread.is_alive():
                return
            self._stop_repeat.clear()
            self._repeat_thread = threading.Thread(
                target=self._repeat_loop, daemon=True)
            self._repeat_thread.start()

    # Max single sleep chunk (seconds) inside the pacing wait. Keeps the loop
    # responsive to on_stop() at low rates without hurting timing accuracy.
    _SLEEP_CHUNK = 0.05

    def _repeat_loop(self):
        """Re-send the stored image at the configured rate.

        Frame-paced like the camera capture loop: send, then sleep the
        remainder of the interval. Timing uses ``time.perf_counter`` (a
        high-resolution monotonic clock) and ``time.sleep`` (high-resolution
        on Python 3.11+ Windows) - NOT ``time.time`` or ``Event.wait``, both
        of which have ~15 ms granularity here and, under load, drag a
        requested 30 fps down to ~11 fps. The interval is re-read each frame
        so it reflects the current config, and the loop exits when stopped or
        when Repeat Send is turned off.
        """
        while not self._stop_repeat.is_set() and self._repeat_enabled():
            frame_start = time.perf_counter()
            self._send_once()

            interval = self._repeat_interval()
            if interval <= 0:
                break

            # Sleep until the next frame deadline, in stop-responsive chunks.
            # deadline - now accounts for the time send() just took, so the
            # period stays at `interval` without drift (best-effort: if a
            # frame overruns the interval, the next fires immediately).
            deadline = frame_start + interval
            while not self._stop_repeat.is_set():
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, self._SLEEP_CHUNK))

    def handle_upload_image(self, file_bytes, filename):
        """API route handler for image upload. Called by the server."""
        self.receive_image(file_bytes, filename)
        return {'success': True, 'filename': filename}

    def on_start(self):
        """Start the base worker; start repeat if an image is already loaded."""
        super().on_start()
        # Normally no image exists yet at deploy time (it is uploaded after),
        # so the timer is started by receive_image. This covers the case an
        # image is already present.
        if self._image_data is not None and self._repeat_enabled():
            self._start_repeat()

    def on_stop(self):
        """Stop the repeat thread, then the base worker."""
        self._stop_repeat.set()
        thread = self._repeat_thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._repeat_thread = None
        super().on_stop()

    def on_close(self):
        """Clean up when the node is deleted."""
        self.on_stop()
