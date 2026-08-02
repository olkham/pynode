"""Multi-object tracking built on ``supervision``'s ByteTrack implementation."""

import logging
from typing import Any, Dict

from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.supervision_utils import (
    import_supervision,
    supervision_missing_message,
    to_sv,
    write_back,
)

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text(
    "Assigns a persistent track ID to each detection across frames using "
    "ByteTrack from the supervision library. Feed it the output of a detector "
    "(YOLO / Inference) and every downstream node can follow objects over time."
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
    ("Tracking Threshold:", "Confidence above which a detection can start a new track (default 0.25)"),
    ("Track Buffer:", "Frames a lost track is remembered before being dropped (default 30)"),
    ("Match Threshold:", "Minimum IoU to associate a detection with an existing track (default 0.8)"),
    ("Min Consecutive Frames:", "Frames an object must be seen before it gets an ID. Raise to 2-3 to "
                                "suppress one-frame ghost tracks (default 1)"),
    ("Source Frame Rate:", "Frame rate of the source. Track Buffer is scaled by this, so setting it "
                           "correctly is what makes the buffer mean real seconds (default 30)"),
    ("Reset Tracker:", "Clear all tracks and restart IDs from 1")
)
_info.add_header("Notes")
_info.add_bullets(
    ("Live tuning:", "Changing any threshold applies immediately and keeps existing track IDs. "
                     "Only Reset clears them."),
    ("Looping video:", "Press Reset (or wire a Reset) when a video restarts, otherwise IDs keep climbing."),
    ("Visualisation:", "Wire an SV Annotate node after this one to draw boxes, labels and traces.")
)
_info.add_header("Requirements")
_info.add_bullets(
    ("supervision:", 'pip install "pynode-flow[vision]"')
)


class SupervisionTrackerNode(BaseNode):
    """ByteTrack object tracker backed by the supervision library."""

    info = str(_info)
    display_name = 'SV Tracker'
    icon = '👀'
    category = 'supervision'
    color = '#5C2D91'
    border_color = '#3F1D63'
    text_color = '#FFFFFF'

    actions = ['reset']

    DEFAULT_CONFIG = {
        'track_thresh': '0.25',
        'track_buffer': '30',
        'match_thresh': '0.8',
        'min_consecutive_frames': '1',
        'frame_rate': '30',
    }

    properties = [
        {
            'name': 'track_thresh',
            'label': 'Tracking Threshold',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['track_thresh'],
            'default': DEFAULT_CONFIG['track_thresh'],
            'help': 'Confidence above which a detection can start a new track',
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
            'name': 'match_thresh',
            'label': 'Match Threshold (IoU)',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['match_thresh'],
            'default': DEFAULT_CONFIG['match_thresh'],
            'help': 'Minimum IoU to associate a detection with an existing track',
        },
        {
            'name': 'min_consecutive_frames',
            'label': 'Min Consecutive Frames',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['min_consecutive_frames'],
            'default': DEFAULT_CONFIG['min_consecutive_frames'],
            'help': 'Frames an object must persist before getting an ID. 2-3 suppresses ghost tracks.',
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
            'name': 'reset',
            'label': 'Reset Tracker',
            'type': 'button',
            'action': 'reset',
        },
    ]

    def __init__(self, node_id=None, name="sv_tracker"):
        self.tracker = None
        self._missing_reported = False
        super().__init__(node_id, name)

    # ------------------------------------------------------------------
    # Tracker lifecycle
    # ------------------------------------------------------------------

    def _tracker_params(self) -> Dict[str, Any]:
        """Read the current ByteTrack tuning values out of config."""
        return {
            'track_activation_threshold': self.get_config_float('track_thresh', 0.25),
            'lost_track_buffer': self.get_config_int('track_buffer', 30),
            'minimum_matching_threshold': self.get_config_float('match_thresh', 0.8),
            'frame_rate': self.get_config_int('frame_rate', 30),
            'minimum_consecutive_frames': self.get_config_int('min_consecutive_frames', 1),
        }

    def _ensure_tracker(self) -> bool:
        """Create the tracker and annotators on first use.

        Returns:
            True when a tracker is available, False when supervision is missing.
        """
        if self.tracker is not None:
            return True

        sv = import_supervision()
        if sv is None:
            if not self._missing_reported:
                self.report_error(supervision_missing_message())
                self._missing_reported = True
            return False

        params = self._tracker_params()
        self.tracker = sv.ByteTrack(**params)
        return True

    def _apply_params(self):
        """Push config values onto a live tracker without discarding tracks.

        Every ByteTrack tuning value is a plain attribute read per update -
        ``__init__`` only derives ``det_thresh`` and ``max_time_lost`` from
        them. Recomputing those two by hand means a threshold tweak in the
        properties panel takes effect on the next frame while existing track
        IDs survive. Rebuilding the tracker here (the previous behaviour) threw
        every ID away on any edit.
        """
        if self.tracker is None:
            return

        params = self._tracker_params()
        self.tracker.track_activation_threshold = params['track_activation_threshold']
        self.tracker.minimum_matching_threshold = params['minimum_matching_threshold']
        self.tracker.minimum_consecutive_frames = params['minimum_consecutive_frames']
        # Mirrors ByteTrack.__init__.
        self.tracker.det_thresh = params['track_activation_threshold'] + 0.1
        self.tracker.max_time_lost = int(
            params['frame_rate'] / 30.0 * params['lost_track_buffer'])

    def configure(self, config):
        super().configure(config)
        self._apply_params()

    def reset(self):
        """Clear all tracks and restart IDs from 1 (UI action)."""
        if self.tracker is not None:
            self.tracker.reset()
            logger.info(f"SV Tracker ({self.id}): tracker reset")
        return {'status': 'reset'}

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def on_input(self, msg, input_index=0):
        if not self._ensure_tracker():
            # Degrade gracefully: without supervision the flow still runs, it
            # just carries no track ids.
            self.send(msg)
            return

        payload = msg.get(MessageKeys.PAYLOAD)
        if not isinstance(payload, dict):
            self.send(msg)
            return

        try:
            detections = to_sv(payload)
            detections = self.tracker.update_with_detections(detections)

            # write_back sets payload.sv (lossless) and payload.detections
            # (interop list). Both come from the same post-tracking object, so
            # class names and track ids stay attached to the right box.
            tracks = write_back(detections, payload)
            payload['tracks'] = tracks
            payload['track_count'] = len(tracks)

            self.send(msg)

        except Exception as e:
            logger.error(f"Error in SupervisionTrackerNode: {e}", exc_info=True)
            self.report_error(f"Tracker error: {e}")
            self.send(msg)
