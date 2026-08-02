"""Bounding-box smoothing built on supervision's DetectionsSmoother."""

import logging

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
    "Smooths bounding-box coordinates over a sliding window of frames, "
    "removing detector jitter. Boxes are matched across frames by track id, "
    "so this node belongs BETWEEN an SV Tracker and whatever draws or "
    "measures the boxes."
)
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with tracked payload.detections (from SV Tracker)")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Same message with smoothed box coordinates (detections, tracks and payload.sv)")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Window Length:", "Frames averaged per box (default 5). Longer = steadier but laggier"),
    ("Reset:", "Clear the smoothing history")
)
_info.add_header("Requirements")
_info.add_bullets(
    ("supervision:", 'pip install "pynode-flow[vision]"')
)


class SupervisionSmootherNode(BaseNode):
    """Sliding-window box smoothing (sv.DetectionsSmoother)."""

    info = str(_info)
    display_name = 'SV Smoother'
    icon = '〰'
    category = 'supervision'
    color = '#7B3FA9'
    border_color = '#5C2D91'
    text_color = '#FFFFFF'

    actions = ['reset']

    DEFAULT_CONFIG = {
        'length': '5',
    }

    properties = [
        {
            'name': 'length',
            'label': 'Window Length (frames)',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['length'],
            'default': DEFAULT_CONFIG['length'],
            'help': 'Frames averaged per box. Longer = steadier but laggier.',
        },
        {
            'name': 'reset',
            'label': 'Reset Smoothing',
            'type': 'button',
            'action': 'reset',
        },
    ]

    def __init__(self, node_id=None, name="sv_smoother"):
        self.smoother = None
        self._built_length = None
        self._missing_reported = False
        self._tracker_warned = False
        super().__init__(node_id, name)

    def _ensure_smoother(self) -> bool:
        sv = import_supervision()
        if sv is None:
            if not self._missing_reported:
                self.report_error(supervision_missing_message())
                self._missing_reported = True
            return False

        length = max(1, self.get_config_int('length', 5))
        if self.smoother is None or length != self._built_length:
            self.smoother = sv.DetectionsSmoother(length=length)
            self._built_length = length
        return True

    def configure(self, config):
        super().configure(config)
        if self.smoother is not None:
            self._ensure_smoother()

    def reset(self):
        """Clear the smoothing history (UI action)."""
        self.smoother = None
        self._ensure_smoother()
        logger.info(f"SV Smoother ({self.id}): history reset")
        return {'status': 'reset'}

    def on_input(self, msg, input_index=0):
        if not self._ensure_smoother():
            self.send(msg)
            return

        payload = msg.get(MessageKeys.PAYLOAD)
        if not isinstance(payload, dict):
            self.send(msg)
            return

        try:
            detections = to_sv(payload)

            if detections.tracker_id is None and len(detections) > 0:
                # DetectionsSmoother matches boxes by track id; without ids it
                # passes detections through unchanged (with an internal
                # warning). Tell the user once, keep the flow running.
                if not self._tracker_warned:
                    self.report_error(
                        "Smoother needs track ids - add an SV Tracker before "
                        "this node")
                    self._tracker_warned = True
                self.send(msg)
                return

            smoothed = self.smoother.update_with_detections(detections)

            entries = write_back(smoothed, payload)
            # Keep the tracker's mirror keys in step with the smoothed boxes.
            if 'tracks' in payload:
                payload['tracks'] = entries
                payload['track_count'] = len(entries)

            self.send(msg)

        except Exception as e:
            logger.error(f"Error in SupervisionSmootherNode: {e}", exc_info=True)
            self.report_error(f"Smoother error: {e}")
            self.send(msg)
