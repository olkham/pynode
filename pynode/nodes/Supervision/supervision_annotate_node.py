"""Configurable detection/track visualisation using supervision's annotators."""

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.supervision_utils import (
    frame_size,
    import_supervision,
    labels_for,
    supervision_missing_message,
    to_sv,
)

logger = logging.getLogger(__name__)

# Canonical application order. Pixel-level effects go first so shapes and text
# drawn later stay crisp on top of them; labels go last so text is never
# covered. The user's multiselect only chooses WHICH annotators run - the
# order is fixed here and documented in the node info.
ANNOTATOR_ORDER = [
    'blur',
    'pixelate',
    'background_overlay',
    'heatmap',
    'color',
    'box',
    'round_box',
    'box_corner',
    'ellipse',
    'circle',
    'triangle',
    'dot',
    'trace',
    'percentage_bar',
    'label',
]

_ANNOTATOR_OPTIONS = [
    {'value': 'box', 'label': 'Box'},
    {'value': 'round_box', 'label': 'Round Box'},
    {'value': 'box_corner', 'label': 'Box Corners'},
    {'value': 'ellipse', 'label': 'Ellipse (feet)'},
    {'value': 'circle', 'label': 'Circle'},
    {'value': 'triangle', 'label': 'Triangle (marker)'},
    {'value': 'dot', 'label': 'Dot'},
    {'value': 'color', 'label': 'Color Fill'},
    {'value': 'label', 'label': 'Label (text)'},
    {'value': 'percentage_bar', 'label': 'Confidence Bar'},
    {'value': 'blur', 'label': 'Blur (privacy)'},
    {'value': 'pixelate', 'label': 'Pixelate (privacy)'},
    {'value': 'background_overlay', 'label': 'Dim Background'},
    {'value': 'trace', 'label': 'Trace (needs tracker)'},
    {'value': 'heatmap', 'label': 'Heat Map'},
]

# Annotators that keep state across frames (and are therefore never rebuilt
# per frame, only on config change or reset).
_STATEFUL = ('trace', 'heatmap')

_info = Info()
_info.add_text(
    "Draws detections/tracks on the frame using the supervision library's "
    "annotators. Pick any combination of visual styles - they are applied in a "
    "fixed sensible order (pixel effects first, shapes next, labels on top)."
)
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with payload.image and payload.detections (or the live payload.sv "
                 "from an upstream Supervision node)")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Same message with payload.image annotated; detections are not modified")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Annotators:", "Which styles to draw. Trace needs track ids (put an SV Tracker upstream); "
                    "Heat Map accumulates positions over time"),
    ("Color By:", "Color objects by class, by track id, or by detection index. 'Track' falls "
                  "back to 'Class' when no track ids are present"),
    ("Thickness / Text Scale:", "'auto' scales with the frame resolution"),
    ("Trace Length:", "How many past positions the trace ribbon keeps"),
    ("Reset:", "Clears accumulated Trace and Heat Map state")
)
_info.add_header("Requirements")
_info.add_bullets(
    ("supervision:", 'pip install "pynode-flow[vision]"')
)


class SupervisionAnnotateNode(BaseNode):
    """Applies a user-selected stack of supervision annotators to the frame."""

    info = str(_info)
    display_name = 'SV Annotate'
    icon = '🎨'
    category = 'supervision'
    color = '#7B3FA9'
    border_color = '#5C2D91'
    text_color = '#FFFFFF'

    actions = ['reset']

    DEFAULT_CONFIG = {
        'annotators': ['box', 'label'],
        'color_lookup': 'class',
        'thickness': 'auto',
        'text_scale': 'auto',
        'show_class': True,
        'show_confidence': True,
        'show_track_id': True,
        'trace_length': '30',
    }

    properties = [
        {
            'name': 'annotators',
            'label': 'Annotators',
            'type': 'multiselect',
            'options': _ANNOTATOR_OPTIONS,
            'default': DEFAULT_CONFIG['annotators'],
        },
        {
            'name': 'color_lookup',
            'label': 'Color By',
            'type': 'select',
            'options': [
                {'value': 'class', 'label': 'Class'},
                {'value': 'track', 'label': 'Track ID'},
                {'value': 'index', 'label': 'Detection Index'},
            ],
            'default': DEFAULT_CONFIG['color_lookup'],
        },
        {
            'name': 'thickness',
            'label': 'Line Thickness',
            'type': 'text',
            'placeholder': 'auto',
            'default': DEFAULT_CONFIG['thickness'],
            'help': "'auto' scales with resolution, or a number (e.g. 2)",
        },
        {
            'name': 'text_scale',
            'label': 'Text Scale',
            'type': 'text',
            'placeholder': 'auto',
            'default': DEFAULT_CONFIG['text_scale'],
            'help': "'auto' scales with resolution, or a number (e.g. 0.5)",
        },
        {
            'name': 'show_class',
            'label': 'Label: Class Name',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['show_class'],
        },
        {
            'name': 'show_confidence',
            'label': 'Label: Confidence',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['show_confidence'],
        },
        {
            'name': 'show_track_id',
            'label': 'Label: Track ID',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['show_track_id'],
        },
        {
            'name': 'trace_length',
            'label': 'Trace Length (frames)',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['trace_length'],
            'default': DEFAULT_CONFIG['trace_length'],
        },
        {
            'name': 'reset',
            'label': 'Reset Trace / Heat Map',
            'type': 'button',
            'action': 'reset',
        },
    ]

    def __init__(self, node_id=None, name="sv_annotate"):
        # name -> live annotator instance, built lazily against the current
        # style config + resolution.
        self._annotators: Dict[str, Any] = {}
        # (lookup_name, thickness, text_scale, trace_length, resolution_wh)
        # the cache was built for; a mismatch rebuilds it.
        self._built_style: Optional[Tuple] = None
        self._missing_reported = False
        self._trace_warned = False
        super().__init__(node_id, name)

    # ------------------------------------------------------------------
    # Annotator construction
    # ------------------------------------------------------------------

    def _selected(self) -> List[str]:
        selected = self.config.get('annotators')
        if not isinstance(selected, list):
            selected = self.DEFAULT_CONFIG['annotators']
        # Fixed canonical order, whatever order the checkboxes were ticked in.
        return [a for a in ANNOTATOR_ORDER if a in selected]

    def _resolve_thickness(self, wh: Tuple[int, int]) -> int:
        sv = import_supervision()
        raw = str(self.config.get('thickness', 'auto')).strip().lower()
        if raw and raw != 'auto':
            try:
                return max(1, int(float(raw)))
            except ValueError:
                pass
        if wh[0] > 0:
            return sv.calculate_optimal_line_thickness(resolution_wh=wh)
        return 2

    def _resolve_text_scale(self, wh: Tuple[int, int]) -> float:
        sv = import_supervision()
        raw = str(self.config.get('text_scale', 'auto')).strip().lower()
        if raw and raw != 'auto':
            try:
                return max(0.1, float(raw))
            except ValueError:
                pass
        if wh[0] > 0:
            return sv.calculate_optimal_text_scale(resolution_wh=wh)
        return 0.5

    def _resolve_lookup(self, has_tracker_ids: bool):
        """Map the config value to a ColorLookup, falling back safely.

        ColorLookup.TRACK raises on detections without tracker_id, so when
        'track' is selected but no ids are present we color by class instead
        of erroring every frame.
        """
        sv = import_supervision()
        name = str(self.config.get('color_lookup', 'class')).lower()
        if name == 'track' and has_tracker_ids:
            return sv.ColorLookup.TRACK
        if name == 'index':
            return sv.ColorLookup.INDEX
        return sv.ColorLookup.CLASS

    def _build(self, name: str, lookup, thickness: int, text_scale: float):
        sv = import_supervision()
        trace_length = self.get_config_int('trace_length', 30)

        if name == 'box':
            return sv.BoxAnnotator(thickness=thickness, color_lookup=lookup)
        if name == 'round_box':
            return sv.RoundBoxAnnotator(thickness=thickness, color_lookup=lookup)
        if name == 'box_corner':
            return sv.BoxCornerAnnotator(thickness=thickness, color_lookup=lookup)
        if name == 'ellipse':
            return sv.EllipseAnnotator(thickness=thickness, color_lookup=lookup)
        if name == 'circle':
            return sv.CircleAnnotator(thickness=thickness, color_lookup=lookup)
        if name == 'triangle':
            return sv.TriangleAnnotator(color_lookup=lookup)
        if name == 'dot':
            return sv.DotAnnotator(color_lookup=lookup)
        if name == 'color':
            return sv.ColorAnnotator(color_lookup=lookup)
        if name == 'label':
            return sv.LabelAnnotator(
                text_scale=text_scale,
                text_thickness=max(1, thickness // 2),
                color_lookup=lookup,
            )
        if name == 'percentage_bar':
            return sv.PercentageBarAnnotator()
        if name == 'blur':
            return sv.BlurAnnotator()
        if name == 'pixelate':
            return sv.PixelateAnnotator()
        if name == 'background_overlay':
            # force_box: dim by bounding box; the mask path needs segmentation
            # masks which arrive in a later phase.
            return sv.BackgroundOverlayAnnotator(force_box=True)
        if name == 'trace':
            return sv.TraceAnnotator(
                trace_length=trace_length, thickness=thickness, color_lookup=lookup)
        if name == 'heatmap':
            return sv.HeatMapAnnotator()
        return None

    def _ensure_annotators(self, lookup, wh: Tuple[int, int]) -> Dict[str, Any]:
        """Return the annotator cache, rebuilding when the style changed.

        Trace/HeatMap keep per-frame state, so the cache persists across frames
        and is only dropped when the visual style itself changes (or on reset).
        """
        thickness = self._resolve_thickness(wh)
        text_scale = self._resolve_text_scale(wh)
        style = (str(lookup), thickness, text_scale,
                 self.get_config_int('trace_length', 30), wh)

        if style != self._built_style:
            self._annotators = {}
            self._built_style = style

        for name in self._selected():
            if name not in self._annotators:
                self._annotators[name] = self._build(name, lookup, thickness, text_scale)

        return self._annotators

    def reset(self):
        """Clear accumulated Trace / Heat Map state (UI action)."""
        for name in _STATEFUL:
            self._annotators.pop(name, None)
        logger.info(f"SV Annotate ({self.id}): stateful annotators reset")
        return {'status': 'reset'}

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def on_input(self, msg, input_index=0):
        sv = import_supervision()
        if sv is None:
            if not self._missing_reported:
                self.report_error(supervision_missing_message())
                self._missing_reported = True
            self.send(msg)
            return

        payload = msg.get(MessageKeys.PAYLOAD)
        if not isinstance(payload, dict) or MessageKeys.IMAGE.PATH not in payload:
            self.send(msg)
            return

        try:
            image, fmt = self.decode_image(payload[MessageKeys.IMAGE.PATH])
            if image is None or fmt is None:
                self.send(msg)
                return

            detections = to_sv(payload)
            has_tracker_ids = detections.tracker_id is not None
            lookup = self._resolve_lookup(has_tracker_ids)
            annotators = self._ensure_annotators(lookup, frame_size(image))

            annotated = image.copy()
            for name in self._selected():
                annotator = annotators.get(name)
                if annotator is None:
                    continue

                if name == 'trace' and not has_tracker_ids:
                    # TraceAnnotator raises on detections without tracker_id
                    # (including empty frames). Needs an SV Tracker upstream.
                    if not self._trace_warned and len(detections) > 0:
                        self.report_error(
                            "Trace annotator needs track ids - add an SV Tracker "
                            "before this node")
                        self._trace_warned = True
                    continue

                if (name == 'heatmap' and len(detections) == 0
                        and not np.any(getattr(annotator, 'heat_mask', None))):
                    # Nothing accumulated yet: normalising an all-zero heat
                    # mask emits numpy divide warnings on every empty frame.
                    continue

                if name == 'label':
                    annotated = annotator.annotate(
                        scene=annotated,
                        detections=detections,
                        labels=labels_for(
                            detections,
                            show_class=self.get_config_bool('show_class', True),
                            show_confidence=self.get_config_bool('show_confidence', True),
                            show_track_id=self.get_config_bool('show_track_id', True),
                        ),
                    )
                else:
                    annotated = annotator.annotate(
                        scene=annotated, detections=detections)

            encoded = self.encode_image(annotated, fmt)
            if encoded is not None:
                payload[MessageKeys.IMAGE.PATH] = encoded

            self.send(msg)

        except Exception as e:
            logger.error(f"Error in SupervisionAnnotateNode: {e}", exc_info=True)
            self.report_error(f"Annotate error: {e}")
            self.send(msg)
