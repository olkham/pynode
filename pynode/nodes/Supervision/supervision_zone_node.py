"""Polygon-zone occupancy monitoring built on supervision's PolygonZone."""

import logging
from typing import Any, Dict, Optional, Set

import numpy as np

from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.supervision_utils import (
    import_supervision,
    parse_points,
    resolve_position,
    supervision_missing_message,
    to_sv,
    write_back,
)

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text(
    "Watches a polygon region: counts the detections inside it, flags each "
    "detection with in_zone, and (with an SV Tracker upstream) emits "
    "enter/exit events as objects move across the boundary."
)
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with payload.detections and optional payload.image")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Every message, with payload.zone_count, in_zone on each detection, and the "
                  "zone drawn on the image when Draw is on"),
    ("Output 1:", "One message per enter/exit event (needs track ids): {event, track_id, "
                  "class_id, class_name, bbox, zone_count}")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Polygon:", "Zone corners as JSON [[x,y],...] in image pixels - or press 'Draw on frame' "
                 "to click them on a live frame"),
    ("Trigger Anchor:", "The point of the box that must be inside (bottom center = feet is the "
                        "usual choice for people)"),
    ("Keep Only In-Zone:", "Drop detections outside the zone from the outgoing message"),
    ("Draw:", "Draw the zone outline, fill and count on the image"),
    ("Reset:", "Forget which tracks are currently inside (event state)")
)
_info.add_header("Requirements")
_info.add_bullets(
    ("supervision:", 'pip install "pynode-flow[vision]"')
)


class SupervisionZoneNode(BaseNode):
    """Polygon zone occupancy counter (sv.PolygonZone)."""

    info = str(_info)
    display_name = 'SV Polygon Zone'
    icon = '⬠'
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
        'polygon': '[[100,100],[540,100],[540,380],[100,380]]',
        'anchor': 'bottom_center',
        'filter_to_zone': False,
        'draw': 'true',
        'opacity': '0.15',
    }

    properties = [
        {
            'name': 'polygon',
            'label': 'Polygon [[x,y],...]',
            'type': 'geometry',
            'geometryType': 'polygon',
            'default': DEFAULT_CONFIG['polygon'],
            'help': 'Zone corners in image pixels. Use Draw on frame to click them visually.',
        },
        {
            'name': 'anchor',
            'label': 'Trigger Anchor',
            'type': 'select',
            'options': [
                {'value': 'bottom_center', 'label': 'Bottom center (feet)'},
                {'value': 'center', 'label': 'Box center'},
                {'value': 'top_center', 'label': 'Top center'},
            ],
            'default': DEFAULT_CONFIG['anchor'],
        },
        {
            'name': 'filter_to_zone',
            'label': 'Keep Only In-Zone Detections',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['filter_to_zone'],
        },
        {
            'name': 'draw',
            'label': 'Draw Zone + Count',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes'},
                {'value': 'false', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['draw'],
        },
        {
            'name': 'opacity',
            'label': 'Fill Opacity',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['opacity'],
            'default': DEFAULT_CONFIG['opacity'],
            'help': '0 = outline only, 1 = solid fill',
        },
        {
            'name': 'reset',
            'label': 'Reset Event State',
            'type': 'button',
            'action': 'reset',
        },
    ]

    def __init__(self, node_id=None, name="sv_zone"):
        self.zone = None
        self.annotator = None
        self._built_for: Optional[tuple] = None
        self._inside: Set[int] = set()      # track_ids currently in the zone
        self._last_frame = None             # raw ndarray for the editor
        self._missing_reported = False
        super().__init__(node_id, name)

    # ------------------------------------------------------------------
    # Zone lifecycle
    # ------------------------------------------------------------------

    def _zone_spec(self) -> Optional[tuple]:
        points = parse_points(self.config.get('polygon', self.DEFAULT_CONFIG['polygon']))
        if points is None:
            return None
        return (tuple(tuple(p) for p in points),
                self.config.get('anchor', 'bottom_center'),
                self.get_config_float('opacity', 0.15))

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
                f"Invalid polygon definition: {self.config.get('polygon')!r} "
                "(expected [[x,y],[x,y],[x,y],...])")
            return False

        if self.zone is not None and spec == self._built_for:
            return True

        points, anchor_key, opacity = spec
        anchor = resolve_position(anchor_key.upper(), default='BOTTOM_CENTER')
        self.zone = sv.PolygonZone(
            polygon=np.array(points, dtype=np.int64),
            triggering_anchors=(anchor,),
        )
        self.annotator = sv.PolygonZoneAnnotator(
            zone=self.zone,
            color=sv.Color.WHITE,
            opacity=max(0.0, min(1.0, opacity)),
        )
        self._built_for = spec
        # A different zone means different membership; forget event state.
        self._inside = set()
        return True

    def configure(self, config):
        super().configure(config)
        if self.zone is not None:
            self._ensure_zone()

    def reset(self):
        """Forget which tracks are inside, so events start fresh (UI action)."""
        self._inside = set()
        logger.info(f"SV Polygon Zone ({self.id}): event state reset")
        return {'status': 'reset'}

    def set_geometry(self, value):
        """Live polygon update from the geometry editor (UI action)."""
        if value:
            self.config['polygon'] = value
            self._ensure_zone()
        return {'status': 'ok', 'polygon': self.config.get('polygon')}

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
            mask = self.zone.trigger(detections) if len(detections) > 0 \
                else np.zeros(0, dtype=bool)

            events = self._track_events(detections, mask)

            if self.get_config_bool('filter_to_zone', False):
                detections = detections[mask]
                write_back(detections, payload)
                for det in payload.get('detections', []):
                    det['in_zone'] = True
            else:
                for i, det in enumerate(payload.get('detections', [])):
                    if isinstance(det, dict) and i < len(mask):
                        det['in_zone'] = bool(mask[i])

            payload['zone_count'] = int(mask.sum())

            if MessageKeys.IMAGE.PATH in payload:
                image, fmt = self.decode_image(payload[MessageKeys.IMAGE.PATH])
                if image is not None:
                    self._last_frame = image  # for the geometry editor
                    if self.get_config_bool('draw', True) and fmt is not None:
                        annotated = self.annotator.annotate(scene=image.copy())
                        encoded = self.encode_image(annotated, fmt)
                        if encoded is not None:
                            payload[MessageKeys.IMAGE.PATH] = encoded

            for event in events:
                self.send({MessageKeys.PAYLOAD: event,
                           MessageKeys.TOPIC: 'zone_event'}, output_index=1)

            self.send(msg, output_index=0)

        except Exception as e:
            logger.error(f"Error in SupervisionZoneNode: {e}", exc_info=True)
            self.report_error(f"Zone error: {e}")
            self.send(msg)

    def _track_events(self, detections, mask) -> list:
        """Diff zone membership against the previous frame (needs track ids)."""
        if detections.tracker_id is None or len(detections) == 0:
            # Without ids we cannot tell WHO entered/left. Exits of vanished
            # tracks are also not detectable on empty frames - acceptable.
            return []

        class_names = detections.data.get('class_name') if detections.data else None
        now_inside: Dict[int, int] = {}   # track_id -> detection index
        for i in range(len(detections)):
            if mask[i]:
                now_inside[int(detections.tracker_id[i])] = i

        zone_count = len(now_inside)
        events = []

        def _event(kind: str, tid: int, index: Optional[int]) -> Dict[str, Any]:
            entry: Dict[str, Any] = {
                'event': kind, 'track_id': tid, 'zone_count': zone_count,
            }
            if index is not None:
                entry['class_id'] = (int(detections.class_id[index])
                                     if detections.class_id is not None else 0)
                entry['class_name'] = (str(class_names[index])
                                       if class_names is not None else '')
                entry['bbox'] = [float(v) for v in detections.xyxy[index]]
            return entry

        seen_ids = {int(t) for t in detections.tracker_id}
        for tid, idx in now_inside.items():
            if tid not in self._inside:
                events.append(_event('enter', tid, idx))
        for tid in sorted(self._inside - set(now_inside)):
            # Only report an exit while the track still exists; a vanished
            # track (left the frame entirely) exits silently.
            if tid in seen_ids:
                idx = int(np.where(detections.tracker_id == tid)[0][0])
                events.append(_event('exit', tid, idx))
                self._inside.discard(tid)
            else:
                self._inside.discard(tid)

        self._inside = set(now_inside)
        return events
