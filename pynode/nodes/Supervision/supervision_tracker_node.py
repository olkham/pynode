"""Multi-object tracking built on Roboflow's ``trackers`` package.

``supervision`` removed ``sv.ByteTrack`` in 0.31.0; the maintained
implementations (ByteTrack, SORT, OC-SORT, BoT-SORT) now live in the separate
``trackers`` package and share one ``update(detections, frame)`` contract that
takes and returns ``sv.Detections``. This node wraps that contract.
"""

import inspect
import logging
import warnings
from typing import Any

from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.supervision_utils import (
    import_supervision,
    import_trackers,
    reid_model_options,
    resolve_torch_device,
    supervision_missing_message,
    to_sv,
    trackers_missing_message,
    use_pynode_reid_cache,
    write_back,
)

logger = logging.getLogger(__name__)

# algorithm config value -> class name in the ``trackers`` package
ALGORITHMS = {
    'bytetrack': 'ByteTrackTracker',
    'sort': 'SORTTracker',
    'ocsort': 'OCSORTTracker',
    'botsort': 'BoTSORTTracker',
}

# Config keys whose change needs a fresh tracker (and therefore new ids).
# Everything else is pushed onto the live tracker.
_STRUCTURAL_KEYS = (
    'algorithm', 'track_buffer', 'frame_rate', 'camera_motion',
    'reid_model', 'reid_device', 'reid_appearance_thresh',
)

_info = Info()
_info.add_text(
    "Assigns a persistent track ID to each detection across frames. Feed it the "
    "output of a detector (YOLO / Inference) and every downstream node can "
    "follow objects over time. Algorithms come from Roboflow's trackers package."
)
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with payload.detections (from a detector) and optional payload.image")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Same message with payload.detections gaining a track_id, plus payload.tracks, "
                  "payload.track_count and the live payload.sv Detections object")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Algorithm:", "ByteTrack (fast, default), SORT (simplest), OC-SORT (better through occlusion "
                   "and non-linear motion) or BoT-SORT (camera-motion compensation and optional "
                   "appearance Re-ID)"),
    ("Tracking Threshold:", "Confidence a detection needs to start a new track (default 0.25)"),
    ("High Confidence Threshold:", "Detections above this are matched first; the rest only revive "
                                   "existing tracks. Blank = same as Tracking Threshold"),
    ("Track Buffer:", "Frames (at 30 FPS) a lost track is remembered before being dropped (default 30)"),
    ("Min IoU:", "Minimum box overlap to associate a detection with an existing track (default 0.2)"),
    ("Min Consecutive Frames:", "Matches a new track needs before it gets an ID. Raise to 2-3 to "
                                "suppress one-frame ghost tracks (default 1)"),
    ("Source Frame Rate:", "Frame rate of the source. Track Buffer is scaled by this, so setting it "
                           "correctly is what makes the buffer mean real seconds (default 30)"),
    ("Keep Untracked:", "Also pass on detections that have no track yet (without a track_id). "
                        "Off = only confirmed tracks leave the node"),
    ("Camera Motion Compensation:", "OC-SORT / BoT-SORT: estimate camera movement from the frame so "
                                    "tracks survive pans and shake. Needs payload.image; costs CPU"),
    ("Re-ID Model:", "BoT-SORT: use an appearance model so a track can be re-attached after an "
                     "occlusion even when the boxes no longer overlap. Needs payload.image"),
    ("Reset Tracker:", "Clear all tracks and restart IDs")
)
_info.add_header("Notes")
_info.add_bullets(
    ("Live tuning:", "Thresholds, Min IoU and Min Consecutive Frames apply immediately and keep "
                     "existing track IDs. Changing the algorithm, buffer, frame rate, camera motion "
                     "or Re-ID settings rebuilds the tracker, which restarts IDs."),
    ("Looping video:", "Press Reset (or wire a Reset) when a video restarts, otherwise IDs keep climbing."),
    ("Visualisation:", "Wire an SV Annotate node after this one to draw boxes, labels and traces."),
    ("Identity across cameras:", "Track IDs are local to this node. Use the SV Re-ID node for an "
                                 "identity that survives leaving the frame or moving between cameras.")
)
_info.add_header("Requirements")
_info.add_bullets(
    ("trackers + supervision:", 'pip install "pynode-flow[vision]"'),
    ("Re-ID model:", 'pip install "pynode-flow[reid]"')
)


class SupervisionTrackerNode(BaseNode):
    """Multi-object tracker backed by the ``trackers`` package."""

    info = str(_info)
    display_name = 'SV Tracker'
    icon = '👀'
    category = 'supervision'
    color = '#5C2D91'
    border_color = '#3F1D63'
    text_color = '#FFFFFF'

    actions = ['reset']

    DEFAULT_CONFIG = {
        'algorithm': 'bytetrack',
        'track_thresh': '0.25',
        'high_thresh': '',
        'track_buffer': '30',
        'min_iou': '0.2',
        'min_consecutive_frames': '1',
        'frame_rate': '30',
        'keep_untracked': False,
        'camera_motion': False,
        'reid_model': 'none',
        'reid_device': 'auto',
        'reid_appearance_thresh': '0.25',
    }

    properties = [
        {
            'name': 'algorithm',
            'label': 'Algorithm',
            'type': 'select',
            'options': [
                {'value': 'bytetrack', 'label': 'ByteTrack'},
                {'value': 'sort', 'label': 'SORT'},
                {'value': 'ocsort', 'label': 'OC-SORT'},
                {'value': 'botsort', 'label': 'BoT-SORT (camera motion / Re-ID)'},
            ],
            'default': DEFAULT_CONFIG['algorithm'],
        },
        {
            'name': 'track_thresh',
            'label': 'Tracking Threshold',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['track_thresh'],
            'default': DEFAULT_CONFIG['track_thresh'],
            'help': 'Confidence a detection needs to start a new track',
            'showIf': {'algorithm': ['bytetrack', 'sort', 'botsort']},
        },
        {
            'name': 'high_thresh',
            'label': 'High Confidence Threshold',
            'type': 'text',
            'placeholder': 'same as Tracking Threshold',
            'default': DEFAULT_CONFIG['high_thresh'],
            'help': 'Detections above this are matched first; lower ones only revive existing tracks',
            'showIf': {'algorithm': ['bytetrack', 'ocsort', 'botsort']},
        },
        {
            'name': 'track_buffer',
            'label': 'Track Buffer (frames)',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['track_buffer'],
            'default': DEFAULT_CONFIG['track_buffer'],
            'help': 'How long a lost track is remembered. Scaled by Source Frame Rate.',
        },
        {
            'name': 'min_iou',
            'label': 'Min IoU',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['min_iou'],
            'default': DEFAULT_CONFIG['min_iou'],
            'help': 'Minimum box overlap to associate a detection with an existing track',
        },
        {
            'name': 'min_consecutive_frames',
            'label': 'Min Consecutive Frames',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['min_consecutive_frames'],
            'default': DEFAULT_CONFIG['min_consecutive_frames'],
            'help': 'Matches a new track needs before getting an ID. 2-3 suppresses ghost tracks.',
        },
        {
            'name': 'frame_rate',
            'label': 'Source Frame Rate',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['frame_rate'],
            'default': DEFAULT_CONFIG['frame_rate'],
            'help': 'Frame rate of the incoming stream. Track Buffer is scaled by this.',
        },
        {
            'name': 'keep_untracked',
            'label': 'Keep Untracked Detections',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['keep_untracked'],
            'help': 'Pass on detections that have no track yet (they carry no track_id)',
        },
        {
            'name': 'camera_motion',
            'label': 'Camera Motion Compensation',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['camera_motion'],
            'help': 'Estimate camera movement from payload.image so tracks survive pans and shake',
            'showIf': {'algorithm': ['ocsort', 'botsort']},
        },
        {
            'name': 'reid_model',
            'label': 'Re-ID Model',
            'type': 'select',
            'options': [{'value': 'none', 'label': 'None (motion only)'}] + reid_model_options(),
            'default': DEFAULT_CONFIG['reid_model'],
            'help': 'Appearance model used to re-attach tracks after occlusion. Needs payload.image.',
            'showIf': {'algorithm': 'botsort'},
        },
        {
            'name': 'reid_device',
            'label': 'Re-ID Device',
            'type': 'select',
            'options': [
                {'value': 'auto', 'label': 'Auto'},
                {'value': 'cpu', 'label': 'CPU'},
                {'value': 'cuda', 'label': 'CUDA (GPU)'},
            ],
            'default': DEFAULT_CONFIG['reid_device'],
            'showIf': {'algorithm': 'botsort'},
        },
        {
            'name': 'reid_appearance_thresh',
            'label': 'Re-ID Appearance Threshold',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['reid_appearance_thresh'],
            'default': DEFAULT_CONFIG['reid_appearance_thresh'],
            'help': 'Maximum appearance distance (0-1) that still counts as the same object',
            'showIf': {'algorithm': 'botsort'},
        },
        {
            'name': 'reset',
            'label': 'Reset Tracker',
            'type': 'button',
            'action': 'reset',
        },
    ]

    def __init__(self, node_id=None, name="sv_tracker"):
        self.tracker = None
        self._structure: tuple | None = None
        self._needs_frame = False
        self._missing_reported = False
        self._build_error: str | None = None
        self._frame_missing_reported = False
        super().__init__(node_id, name)

    # ------------------------------------------------------------------
    # Config parsing
    # ------------------------------------------------------------------

    def _float(self, key: str, default: float) -> float:
        """Read a float from config, tolerating blank / malformed text."""
        try:
            return float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _int(self, key: str, default: int) -> int:
        try:
            return int(float(self.config.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _algorithm(self) -> str:
        name = str(self.config.get('algorithm', 'bytetrack') or 'bytetrack').strip().lower()
        return name if name in ALGORITHMS else 'bytetrack'

    def _reid_model_name(self) -> str:
        if self._algorithm() != 'botsort':
            return ''
        name = str(self.config.get('reid_model', 'none') or 'none').strip()
        return '' if name.lower() == 'none' else name

    def _tunable_params(self) -> dict[str, Any]:
        """Values that are plain attributes on a live tracker.

        Keyed by every name the different tracker classes use for the same
        idea; :meth:`_apply_params` and :meth:`_build_tracker` keep only the
        ones the chosen class actually has.
        """
        track_thresh = min(max(self._float('track_thresh', 0.25), 0.0), 1.0)
        high_raw = str(self.config.get('high_thresh', '') or '').strip()
        try:
            high_thresh = min(max(float(high_raw), 0.0), 1.0) if high_raw else track_thresh
        except ValueError:
            high_thresh = track_thresh
        min_iou = min(max(self._float('min_iou', 0.2), 0.0), 1.0)

        return {
            'track_activation_threshold': track_thresh,
            'high_conf_det_threshold': high_thresh,
            'minimum_iou_threshold': min_iou,
            # BoT-SORT names its primary association threshold differently.
            'minimum_iou_threshold_first_assoc': min_iou,
            'minimum_consecutive_frames': max(self._int('min_consecutive_frames', 1), 1),
        }

    def _structure_key(self) -> tuple:
        return tuple(str(self.config.get(key, '')) for key in _STRUCTURAL_KEYS)

    # ------------------------------------------------------------------
    # Tracker lifecycle
    # ------------------------------------------------------------------

    def _build_tracker(self, trackers_module):
        """Instantiate the configured tracker class."""
        algorithm = self._algorithm()
        cls = getattr(trackers_module, ALGORITHMS[algorithm])
        accepted = inspect.signature(cls.__init__).parameters

        candidates = dict(self._tunable_params())
        candidates.update({
            'lost_track_buffer': max(self._int('track_buffer', 30), 0),
            'frame_rate': max(self._float('frame_rate', 30.0), 1.0),
            'enable_cmc': self.get_config_bool('camera_motion', False),
        })
        kwargs = {k: v for k, v in candidates.items() if k in accepted}

        needs_frame = bool(kwargs.get('enable_cmc'))

        reid_name = self._reid_model_name()
        if reid_name and 'reid_model' in accepted:
            from reid import ReIDModel  # type: ignore

            use_pynode_reid_cache()
            device, warning = resolve_torch_device(self.config.get('reid_device', 'auto'))
            if warning:
                self.report_error(warning)
            kwargs['reid_model'] = ReIDModel.from_pretrained(reid_name, device=device)
            kwargs['reid_config'] = trackers_module.ReIDConfig(
                appearance_threshold=min(max(self._float('reid_appearance_thresh', 0.25), 0.0), 1.0))
            needs_frame = True

        self._needs_frame = needs_frame
        return cls(**kwargs)

    def _ensure_tracker(self) -> bool:
        """Create (or rebuild) the tracker on demand.

        Returns:
            True when a tracker is available, False when a dependency is
            missing or the tracker could not be built.
        """
        structure = self._structure_key()
        if self.tracker is not None and structure == self._structure:
            return True
        if self._build_error is not None and structure == self._structure:
            # Already failed with this exact configuration; don't retry (and
            # re-report) on every frame.
            return False

        if import_supervision() is None:
            self._report_missing(supervision_missing_message())
            return False
        trackers_module = import_trackers()
        if trackers_module is None:
            self._report_missing(trackers_missing_message())
            return False

        self._structure = structure
        self._frame_missing_reported = False
        try:
            self.tracker = self._build_tracker(trackers_module)
            self._build_error = None
        except ImportError:
            self.tracker = None
            self._build_error = ('Re-ID model support is not installed. '
                                 'Run: pip install "pynode-flow[reid]"')
            self.report_error(self._build_error)
            return False
        except Exception as e:
            self.tracker = None
            self._build_error = f"Could not create tracker: {e}"
            logger.error(f"SV Tracker ({self.id}): {self._build_error}", exc_info=True)
            self.report_error(self._build_error)
            return False

        logger.info(f"SV Tracker ({self.id}): using {type(self.tracker).__name__}")
        return True

    def _report_missing(self, message: str):
        if not self._missing_reported:
            self.report_error(message)
            self._missing_reported = True

    def _apply_params(self):
        """Push threshold edits onto a live tracker without discarding tracks.

        Every value in :meth:`_tunable_params` is a plain attribute the tracker
        reads on each update, so a tweak in the properties panel takes effect
        on the next frame while existing track IDs survive. Structural changes
        are picked up by :meth:`_ensure_tracker` instead.
        """
        if self.tracker is None:
            return
        for name, value in self._tunable_params().items():
            if hasattr(self.tracker, name):
                setattr(self.tracker, name, value)

    def configure(self, config):
        config = dict(config)
        # Flows saved before the move to the `trackers` package carry
        # sv.ByteTrack's `match_thresh`, which was an IoU *distance* (0.8 meant
        # "IoU of at least 0.2"). Translate it instead of silently reusing the
        # number as an IoU, which would break association.
        legacy = config.pop('match_thresh', None)
        if legacy is not None and 'min_iou' not in config:
            try:
                config['min_iou'] = str(round(min(max(1.0 - float(legacy), 0.0), 1.0), 4))
            except (TypeError, ValueError):
                pass
        super().configure(config)
        self._apply_params()

    def reset(self):
        """Clear all tracks and restart IDs (UI action)."""
        if self.tracker is not None:
            self.tracker.reset()
            logger.info(f"SV Tracker ({self.id}): tracker reset")
        return {'status': 'reset'}

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def _frame_for(self, payload: dict[str, Any]):
        """Decode the frame only for trackers that actually look at it."""
        if not self._needs_frame:
            return None
        image = None
        if MessageKeys.IMAGE.PATH in payload:
            image, _ = self.decode_image(payload[MessageKeys.IMAGE.PATH])
        if image is None and not self._frame_missing_reported:
            self._frame_missing_reported = True
            self.report_error(
                "Camera motion compensation / Re-ID need payload.image, but the "
                "message has none. Tracking continues on box motion only.")
        return image

    def on_input(self, msg, input_index=0):
        payload = msg.get(MessageKeys.PAYLOAD)
        if not isinstance(payload, dict) or not self._ensure_tracker():
            # Degrade gracefully: without a tracker the flow still runs, it
            # just carries no track ids.
            self.send(msg)
            return

        try:
            detections = to_sv(payload)
            frame = self._frame_for(payload)

            if self._needs_frame and frame is None and getattr(self.tracker, 'reid_model', None) is not None:
                # A Re-ID tracker raises without a frame; skip the update so
                # the flow keeps running.
                self.send(msg)
                return

            tracker: Any = self.tracker
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                detections = tracker.update(detections, frame)

            # The trackers package returns every detection and marks the ones
            # without a confirmed track with tracker_id -1.
            if detections.tracker_id is not None and len(detections) > 0:
                tracked = detections.tracker_id >= 0
                if not self.get_config_bool('keep_untracked', False):
                    detections = detections[tracked]

            # write_back sets payload.sv (lossless) and payload.detections
            # (interop list). Both come from the same post-tracking object, so
            # class names and track ids stay attached to the right box.
            entries = write_back(detections, payload)
            tracks = [e for e in entries if 'track_id' in e]
            payload['tracks'] = tracks
            payload['track_count'] = len(tracks)

            self.send(msg)

        except Exception as e:
            logger.error(f"Error in SupervisionTrackerNode: {e}", exc_info=True)
            self.report_error(f"Tracker error: {e}")
            self.send(msg)
