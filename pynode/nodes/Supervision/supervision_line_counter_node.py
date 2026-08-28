"""Line-crossing counter built on supervision's LineZone."""

import logging
import warnings
from typing import Any, Dict, Optional

# supervision <=0.27 line_zone.py uses np.cross on 2-D vectors, which NumPy 2
# deprecates. It fires inside supervision, not our code - silence just that
# message so it cannot noise server logs.
warnings.filterwarnings(
    'ignore', message='Arrays of 2-dimensional vectors are deprecated.*')

from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.supervision_utils import (
    import_supervision,
    parse_line,
    supervision_missing_message,
    to_sv,
)

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text(
    "Counts tracked objects crossing a virtual line, in both directions. "
    "The classic people/vehicle counting setup: put an SV Tracker before this "
    "node - crossings are detected per track id, so untracked detections are "
    "not counted."
)
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with tracked payload.detections (from SV Tracker) and optional payload.image")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Every message, with payload.line_in / line_out totals (plus per-class-name "
                  "counts) and the line drawn on the image when Draw is on"),
    ("Output 1:", "One message per crossing event: {event, direction, track_id, class_id, "
                  "class_name, bbox, in_count, out_count}")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Line:", "The counting line as x1,y1,x2,y2 in image pixels - or press 'Draw on frame' "
              "to drag it on a live frame"),
    ("Trigger Anchors:", "Which part of the box must cross: all four corners (strict), center, "
                         "or bottom center (feet)"),
    ("Min Crossing Frames:", "Frames the anchor must stay on the new side before counting (debounce)"),
    ("Draw:", "Draw the line and in/out counts on the image"),
    ("Reset:", "Zero both counters")
)
_info.add_header("Notes")
_info.add_bullets(
    ("Direction:", "'in' and 'out' are the two sides of the line; swap the endpoints to flip them"),
    ("Live edit:", "Drawing a new line applies immediately and resets the counts")
)
_info.add_header("Requirements")
_info.add_bullets(
    ("supervision:", 'pip install "pynode-flow[vision]"')
)

_ANCHOR_PRESETS = {
    # None -> use supervision's default (all four box corners)
    'corners': None,
    'center': ('CENTER',),
    'bottom_center': ('BOTTOM_CENTER',),
}


class SupervisionLineCounterNode(BaseNode):
    """Bidirectional line-crossing counter (sv.LineZone)."""

    info = str(_info)
    display_name = 'SV Line Counter'
    icon = '🚦'
    category = 'supervision'
    color = '#7B3FA9'
    border_color = '#5C2D91'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 2

    actions = ['reset', 'set_geometry']

    # NOTE: route names are global URL rules shared across node types -
    # 'frame' is already claimed by ImageViewerNode with a different handler,
    # so this must use a distinct name.
    api_routes = [
        {'route': 'editor_frame', 'methods': ['GET'], 'handler': 'get_editor_frame'},
    ]

    DEFAULT_CONFIG = {
        'line': '160,240,480,240',
        'anchors': 'corners',
        'min_crossing_frames': '1',
        'draw': 'true',
    }

    # Editor UI for this node's custom property type (see BaseNode.ui_assets).
    ui_assets = {'js': ['ui/geometry.js']}

    properties = [
        {
            'name': 'line',
            'label': 'Line (x1,y1,x2,y2)',
            'type': 'geometry',
            'geometryType': 'line',
            'default': DEFAULT_CONFIG['line'],
            'help': 'Counting line in image pixels. Use Draw on frame to place it visually.',
        },
        {
            'name': 'anchors',
            'label': 'Trigger Anchors',
            'type': 'select',
            'options': [
                {'value': 'corners', 'label': 'All four corners (strict)'},
                {'value': 'center', 'label': 'Box center'},
                {'value': 'bottom_center', 'label': 'Bottom center (feet)'},
            ],
            'default': DEFAULT_CONFIG['anchors'],
        },
        {
            'name': 'min_crossing_frames',
            'label': 'Min Crossing Frames',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['min_crossing_frames'],
            'default': DEFAULT_CONFIG['min_crossing_frames'],
            'help': 'Debounce: frames the object must stay on the new side before counting',
        },
        {
            'name': 'draw',
            'label': 'Draw Line + Counts',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes'},
                {'value': 'false', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['draw'],
        },
        {
            'name': 'reset',
            'label': 'Reset Counts',
            'type': 'button',
            'action': 'reset',
        },
    ]

    def __init__(self, node_id=None, name="sv_line_counter"):
        self.line_zone = None
        self.annotator = None
        self._built_for: Optional[tuple] = None   # (line, anchors, min_frames)
        # Per-class-name counts accumulated from crossing events (LineZone's
        # own per-class dicts are keyed by class_id).
        self.class_counts: Dict[str, Dict[str, int]] = {'in': {}, 'out': {}}
        self._last_frame = None                   # raw ndarray for the editor
        self._missing_reported = False
        self._tracker_warned = False
        super().__init__(node_id, name)

    # ------------------------------------------------------------------
    # Zone lifecycle
    # ------------------------------------------------------------------

    def _zone_spec(self) -> Optional[tuple]:
        line = parse_line(self.config.get('line', self.DEFAULT_CONFIG['line']))
        if line is None:
            return None
        return (line, self.config.get('anchors', 'corners'),
                self.get_config_int('min_crossing_frames', 1))

    def _ensure_zone(self) -> bool:
        sv = import_supervision()
        if sv is None:
            if not self._missing_reported:
                self.report_error(supervision_missing_message())
                self._missing_reported = True
            return False

        spec = self._zone_spec()
        if spec is None:
            self.report_error(
                f"Invalid line definition: {self.config.get('line')!r} "
                "(expected x1,y1,x2,y2)")
            return False

        if self.line_zone is not None and spec == self._built_for:
            return True

        (p1, p2), anchors_key, min_frames = spec
        kwargs: Dict[str, Any] = {
            'start': sv.Point(int(p1[0]), int(p1[1])),
            'end': sv.Point(int(p2[0]), int(p2[1])),
            'minimum_crossing_threshold': max(1, min_frames),
        }
        preset = _ANCHOR_PRESETS.get(anchors_key)
        if preset is not None:
            kwargs['triggering_anchors'] = [getattr(sv.Position, a) for a in preset]

        # LineZone has no reset() and no mutable line - a new spec means a new
        # zone, and with it fresh counters.
        self.line_zone = sv.LineZone(**kwargs)
        self.annotator = sv.LineZoneAnnotator(text_orient_to_line=True)
        self.class_counts = {'in': {}, 'out': {}}
        self._built_for = spec
        return True

    def configure(self, config):
        super().configure(config)
        # Rebuild only if the zone exists and the spec really changed
        # (_ensure_zone compares against _built_for).
        if self.line_zone is not None:
            self._ensure_zone()

    def reset(self):
        """Zero both counters (UI action)."""
        self._built_for = None
        self.line_zone = None
        self._ensure_zone()
        logger.info(f"SV Line Counter ({self.id}): counters reset")
        return {'status': 'reset'}

    def set_geometry(self, value):
        """Live line update from the geometry editor (UI action)."""
        if value:
            self.config['line'] = value
            self._ensure_zone()
        return {'status': 'ok', 'line': self.config.get('line')}

    def get_editor_frame(self):
        """Serve the last input frame to the draw-on-frame editor."""
        if self._last_frame is None:
            return {'data': None}
        encoded = self.encode_image(self._last_frame, 'jpeg_base64_dict')
        if not isinstance(encoded, dict):
            return {'data': None}
        return {'data': encoded.get(MessageKeys.IMAGE.DATA),
                'width': int(self._last_frame.shape[1]),
                'height': int(self._last_frame.shape[0])}

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def on_input(self, msg, input_index=0):
        if not self._ensure_zone():
            self.send(msg)
            return

        payload = msg.get(MessageKeys.PAYLOAD)
        if not isinstance(payload, dict):
            self.send(msg)
            return

        try:
            detections = to_sv(payload)

            if detections.tracker_id is None and len(detections) > 0:
                if not self._tracker_warned:
                    self.report_error(
                        "Line counter needs track ids - add an SV Tracker "
                        "before this node")
                    self._tracker_warned = True
                self.send(msg)
                return

            crossed_in, crossed_out = self.line_zone.trigger(detections)

            # Emit one event message per crossing BEFORE mutating/sending the
            # main message (send() contract: no touching a msg after send).
            events = []
            class_names = detections.data.get('class_name') if detections.data else None
            for i in range(len(detections)):
                direction = 'in' if crossed_in[i] else ('out' if crossed_out[i] else None)
                if direction is None:
                    continue
                class_name = (str(class_names[i])
                              if class_names is not None and i < len(class_names) else '')
                bucket = self.class_counts[direction]
                key = class_name or str(int(detections.class_id[i]))
                bucket[key] = bucket.get(key, 0) + 1
                events.append({
                    'event': 'line_crossing',
                    'direction': direction,
                    'track_id': int(detections.tracker_id[i]),
                    'class_id': int(detections.class_id[i]) if detections.class_id is not None else 0,
                    'class_name': class_name,
                    'bbox': [float(v) for v in detections.xyxy[i]],
                    'in_count': int(self.line_zone.in_count),
                    'out_count': int(self.line_zone.out_count),
                })

            payload['line_in'] = int(self.line_zone.in_count)
            payload['line_out'] = int(self.line_zone.out_count)
            payload['line_in_by_class'] = dict(self.class_counts['in'])
            payload['line_out_by_class'] = dict(self.class_counts['out'])

            if MessageKeys.IMAGE.PATH in payload:
                image, fmt = self.decode_image(payload[MessageKeys.IMAGE.PATH])
                if image is not None:
                    self._last_frame = image  # for the geometry editor
                    if self.get_config_bool('draw', True) and fmt is not None:
                        annotated = self.annotator.annotate(
                            frame=image.copy(), line_counter=self.line_zone)
                        encoded = self.encode_image(annotated, fmt)
                        if encoded is not None:
                            payload[MessageKeys.IMAGE.PATH] = encoded

            for event in events:
                self.send({MessageKeys.PAYLOAD: event,
                           MessageKeys.TOPIC: 'line_crossing'}, output_index=1)

            self.send(msg, output_index=0)

        except Exception as e:
            logger.error(f"Error in SupervisionLineCounterNode: {e}", exc_info=True)
            self.report_error(f"Line counter error: {e}")
            self.send(msg)
