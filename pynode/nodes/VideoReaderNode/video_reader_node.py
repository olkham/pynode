"""
Video Reader node - plays a video file frame-by-frame with transport
controls (play/pause, stop, step) rendered on the node itself.
"""

import base64
import os
import queue
import threading
from typing import Any, Dict, Optional

import cv2

from pynode.nodes.base_node import BaseNode, FramePacer, Info, MessageKeys

_info = Info()
_info.add_text("Reads a video file and outputs its frames as messages. By default frames "
               "are sent as raw numpy arrays (no encoding overhead); enable 'Encode as "
               "JPEG' to send base64 JPEG-encoded frames instead. Playback is driven by "
               "the transport controls on the node: play/pause, stop, and single-frame "
               "stepping.")
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Frame message (payload.image numpy array or JPEG base64, depending "
                  "on config) with frame index, total frame count and source path."),
)
_info.add_header("Transport Controls")
_info.add_bullets(
    ("⏮ Step back:", "Show the previous frame (while paused/stopped)."),
    ("▶/⏸ Play/Pause:", "Toggle playback from the current position. The icon "
                        "shows what the next click will do: ▶ while paused/"
                        "stopped, ⏸ while playing."),
    ("⏹ Stop:", "Halt playback and seek back to the first frame."),
    ("⏭ Step forward:", "Show the next frame (while paused/stopped)."),
    ("Progress bar:", "Drag the slider along the bottom of the node to scrub "
                      "to any point in the video."),
)
_info.add_header("Properties")
_info.add_bullets(
    ("Video File:", "Upload a video or enter a path manually."),
    ("Frame Rate:", "Playback FPS override; 0 uses the video's native rate."),
    ("Loop:", "Restart from the first frame when the video ends."),
    ("Encode as JPEG:", "Output as base64 JPEG or raw numpy array (default)."),
    ("JPEG Quality:", "Encoding quality for the emitted frames when JPEG is enabled (1-100)."),
)
_info.add_header("Output Format")
_info.add_bullets(
    (f"{MessageKeys.PAYLOAD}.image:", "Image data (JPEG base64 or numpy array depending on config)."),
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
            # activeIcon/activeTitle are swapped in by the frontend while the
            # node reports playing=true, so the button always shows the action
            # the next click will take.
            {'icon': '▶', 'action': 'play_pause', 'title': 'Play',
             'activeIcon': '⏸', 'activeTitle': 'Pause'},
            {'icon': '⏹', 'action': 'stop', 'title': 'Stop (back to first frame)'},
            {'icon': '⏭', 'action': 'step_next', 'title': 'Step forward one frame'},
        ],
    }

    # UI-triggerable actions (see BaseNode.actions)
    actions = ['play_pause', 'stop', 'step_prev', 'step_next', 'seek']

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
        MessageKeys.CAMERA.ENCODE_JPEG: False,
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
            'name': MessageKeys.CAMERA.ENCODE_JPEG,
            'label': 'Encode as JPEG',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG[MessageKeys.CAMERA.ENCODE_JPEG],
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
        # Prefetch pipeline (playback only): _decode_loop reads ahead into
        # _prefetch_q, _playback_loop drains it on a fixed schedule. See
        # _decode_loop for why the read is decoupled from the emit.
        self._prefetch_q: Optional[queue.Queue] = None
        self._decode_thread: Optional[threading.Thread] = None
        # Index of the next frame the DECODER will read. Runs ahead of
        # _frame_index (the display position) by up to _PREFETCH_DEPTH.
        self._decode_index = 0
        # Bumped on every seek; frames queued under an older generation are
        # discarded by the emit loop instead of being shown after the seek.
        self._generation = 0
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

    def seek(self, target):
        """Seek to a specific frame index (driven by the progress slider)."""
        with self._transport_lock:
            if not self._ensure_capture():
                return
            try:
                index = int(target)
            except (TypeError, ValueError):
                return
            with self._cap_lock:
                if self._total_frames:
                    index = max(0, min(index, self._total_frames - 1))
                else:
                    index = max(0, index)
                if self._playing:
                    # Reposition and let the pipeline pick it up: bumping the
                    # generation makes the decoder re-seek and the emit loop
                    # discard anything already queued from before the seek.
                    self._frame_index = index
                    self._decode_index = index
                    self._generation += 1
                    self._drain_prefetch()
                    return
            # Paused/stopped: show the requested frame immediately.
            self._emit_frame_at(index)

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
        """Seek to `index` (if needed), read one frame and send it.

        Used by the paused-only transport actions (step/seek/stop). Playback
        goes through the prefetch pipeline instead - see _decode_loop.
        """
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

        return self._send_frame(index, frame, total, path)

    def _send_frame(self, index: int, frame, total: int,
                    path: Optional[str]) -> bool:
        """Build the frame message for `frame` and send it downstream."""
        if self.get_config_bool(MessageKeys.CAMERA.ENCODE_JPEG, False):
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
        else:
            # Raw numpy array (default) - mirrors CameraNode's non-encoded output.
            image_payload = {
                MessageKeys.IMAGE.FORMAT: 'bgr',
                MessageKeys.IMAGE.ENCODING: 'numpy',
                MessageKeys.IMAGE.DATA: frame,
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

    # Frames decoded ahead of the emit schedule. Decode cost is bursty
    # (measured 6-119 ms/frame on a 1080p H.264 file whose *mean* is 22 ms);
    # a few frames of slack let the fast frames pay for the slow ones. Costs
    # depth x frame bytes of RAM (~25 MB for 4 x 1080p BGR).
    _PREFETCH_DEPTH = 4

    # Max single sleep chunk (seconds) inside the pacing wait, so a paused/
    # stopped transport action is honoured promptly at low frame rates.
    _SLEEP_CHUNK = 0.05

    def _put_prefetch(self, q: queue.Queue, item) -> bool:
        """Block until `item` is queued, or playback stops. Returns whether
        it was queued.

        Never an unconditional blocking put: the emit loop can stop draining
        at any moment (pause/stop), and the decoder must notice rather than
        park forever on a full queue.
        """
        while self._playing:
            try:
                q.put(item, timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    def _drain_prefetch(self):
        """Discard queued frames (called on seek and when playback ends)."""
        q = self._prefetch_q
        if q is None:
            return
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return

    def _decode_loop(self, loop: bool, q: queue.Queue):
        """Decoder thread: keep the prefetch queue topped up.

        The queue is passed in rather than read off self so that a decoder
        outliving its join timeout keeps writing to its own (now orphaned)
        queue instead of tripping over _prefetch_q being cleared.

        Decoding is decoupled from emitting because frame decode cost is
        bursty: an I-frame can take 4x the frame budget while the P-frames
        around it take a fraction of it. Reading inline with the pacing (the
        previous design) gave every slow frame a permanent late penalty that
        the fast frames could never repay, capping a 30 fps file at ~24 fps.
        Reading ahead lets the queue absorb the spikes.

        This is the only thing that touches the capture while playing.
        """
        gen = -1
        # Consecutive failed reads while looping; bounded so a file that
        # always fails to read can't spin this thread forever.
        failures = 0
        while self._playing:
            with self._cap_lock:
                cap = self._cap
                if cap is None or not cap.isOpened():
                    break

                if gen != self._generation:
                    # Fresh start, or a seek landed: resync to the new spot.
                    gen = self._generation
                    if int(cap.get(cv2.CAP_PROP_POS_FRAMES)) != self._decode_index:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, self._decode_index)

                index = self._decode_index
                if self._total_frames and index >= self._total_frames:
                    if not loop:
                        break
                    index = 0
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

                ret, frame = cap.read()
                if not ret or frame is None:
                    # Read failure, or the end of a file whose frame count
                    # was unknown/wrong. Rewind rather than bumping the
                    # generation: frames already queued are still valid and
                    # should play out before the wrap.
                    failures += 1
                    if not (loop and self._total_frames) or failures > 3:
                        break
                    self._decode_index = 0
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                failures = 0
                self._decode_index = index + 1

            # Hand off outside _cap_lock so a full queue never blocks the
            # transport actions.
            self._put_prefetch(q, (gen, index, frame))

        # Sentinel: tell the emit loop no more frames are coming. Must be a
        # blocking put - dropping it on a full queue would leave the emit
        # loop spinning and _playing stuck True at the end of the video.
        self._put_prefetch(q, (gen, -1, None))

    def _playback_loop(self):
        """Worker thread: emit prefetched frames on a fixed schedule.

        Pacing is delegated to FramePacer (absolute deadline, so a fast
        frame repays a slow one); see that class for why the naive
        sleep(interval - elapsed) form capped this node at ~23 fps.
        """
        fps = self.get_config_float(MessageKeys.CAMERA.FPS, 0)
        if fps <= 0:
            fps = self._native_fps
        if fps <= 0:
            fps = 30.0
        frame_interval = 1.0 / fps
        loop = self.get_config_bool(MessageKeys.VIDEO.LOOP, False)

        prefetch_q: queue.Queue = queue.Queue(maxsize=self._PREFETCH_DEPTH)
        self._prefetch_q = prefetch_q
        with self._cap_lock:
            self._decode_index = self._frame_index
            self._generation += 1
        self._decode_thread = threading.Thread(target=self._decode_loop,
                                               args=(loop, prefetch_q),
                                               daemon=True)
        self._decode_thread.start()

        # Tight catch-up bound on purpose: the prefetch queue already absorbs
        # the decode spikes, so the pacer only has residual jitter to trim.
        # Letting it repay more just emits catch-up bursts - measured here as
        # inter-frame stdev 9.7 ms at the default bound vs 4.7 ms at 1.0.
        pacer = FramePacer(frame_interval, running=lambda: self._playing,
                           sleep_chunk=self._SLEEP_CHUNK, max_catchup=1.0)
        try:
            while self._playing:
                try:
                    gen, index, frame = prefetch_q.get(timeout=0.1)
                except queue.Empty:
                    # Backstop for a lost sentinel: a seek landing in the
                    # gap between the decoder exiting and this loop reading
                    # its sentinel would drain it. Dead decoder + empty
                    # queue means nothing more is coming, so don't spin.
                    decoder = self._decode_thread
                    if decoder is not None and not decoder.is_alive():
                        break
                    continue

                if frame is None:
                    break  # decoder finished (end of video, or read failure)
                if gen != self._generation:
                    continue  # queued before a seek - stale, drop it

                total = self._total_frames
                path = self._video_path
                self._frame_index = index + 1
                self._send_frame(index, frame, total, path)

                if not pacer.wait():
                    break
        finally:
            self._playing = False
            decoder = self._decode_thread
            if decoder is not None and decoder.is_alive():
                # Unblock a decoder parked on a full queue, then let it exit.
                self._drain_prefetch()
                decoder.join(timeout=1.0)
            self._decode_thread = None
            self._drain_prefetch()
            self._prefetch_q = None
