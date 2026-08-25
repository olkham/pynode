"""Multi-criteria detection filtering built on supervision's Detections ops."""

import logging
from typing import Any, Dict, List, Optional, Set

import numpy as np

from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.supervision_utils import (
    import_supervision,
    supervision_missing_message,
    sv_to_list,
    to_sv,
)

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text(
    "Filters detections on several criteria at once - confidence range, class "
    "allow/deny lists, box area, aspect ratio, top-K - and can finish with "
    "NMS or NMM de-duplication. Combines what Confidence Filter and Label "
    "Filter do and adds the geometric criteria."
)
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with payload.detections (tracked or not)")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Message with the detections that passed every criterion"),
    ("Output 1:", "Message with the detections rejected by the criteria "
                  "(NMS/NMM-suppressed duplicates are dropped, not rejected)")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Confidence Min/Max:", "Keep detections inside the range. Empty = no bound"),
    ("Allow/Deny Classes:", "Comma lists of class names (or numeric ids). Allow list empty = allow all"),
    ("Area Min/Max:", "Box area bounds in px². Empty = no bound"),
    ("Aspect Min/Max:", "Box width/height ratio bounds. Empty = no bound"),
    ("Top K:", "After the other criteria, keep only the K most confident. Empty = all"),
    ("De-duplicate:", "Off, NMS (suppress overlaps) or NMM (merge overlaps), with IoU/IoS metric "
                      "and optional class-agnostic matching")
)
_info.add_header("Requirements")
_info.add_bullets(
    ("supervision:", 'pip install "pynode-flow[vision]"')
)


def _parse_float(value: Any) -> Optional[float]:
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_class_list(value: Any) -> Set[str]:
    """Lower-cased set of class tokens (names and/or numeric ids as strings)."""
    return {t.strip().lower() for t in str(value or '').split(',') if t.strip()}


class SupervisionFilterNode(BaseNode):
    """Combined detection filter with NMS/NMM (sv.Detections operations)."""

    info = str(_info)
    display_name = 'SV Detection Filter'
    icon = '🧹'
    category = 'supervision'
    color = '#7B3FA9'
    border_color = '#5C2D91'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 2

    DEFAULT_CONFIG = {
        'min_confidence': '',
        'max_confidence': '',
        'allow_classes': '',
        'deny_classes': '',
        'min_area': '',
        'max_area': '',
        'min_aspect': '',
        'max_aspect': '',
        'top_k': '',
        'dedupe': 'off',
        'dedupe_threshold': '0.5',
        'class_agnostic': False,
        'overlap_metric': 'iou',
    }

    properties = [
        {'name': 'min_confidence', 'label': 'Confidence Min', 'type': 'text',
         'default': '', 'placeholder': 'e.g. 0.5 (empty = off)'},
        {'name': 'max_confidence', 'label': 'Confidence Max', 'type': 'text',
         'default': '', 'placeholder': 'empty = off'},
        {'name': 'allow_classes', 'label': 'Allow Classes', 'type': 'text',
         'default': '', 'placeholder': 'person, car (empty = all)',
         'help': 'Comma list of class names or numeric ids to keep'},
        {'name': 'deny_classes', 'label': 'Deny Classes', 'type': 'text',
         'default': '', 'placeholder': 'e.g. bench',
         'help': 'Comma list of class names or numeric ids to drop'},
        {'name': 'min_area', 'label': 'Area Min (px²)', 'type': 'text',
         'default': '', 'placeholder': 'e.g. 400 (empty = off)'},
        {'name': 'max_area', 'label': 'Area Max (px²)', 'type': 'text',
         'default': '', 'placeholder': 'empty = off'},
        {'name': 'min_aspect', 'label': 'Aspect Min (w/h)', 'type': 'text',
         'default': '', 'placeholder': 'e.g. 0.2 (empty = off)'},
        {'name': 'max_aspect', 'label': 'Aspect Max (w/h)', 'type': 'text',
         'default': '', 'placeholder': 'e.g. 1.5 (empty = off)'},
        {'name': 'top_k', 'label': 'Top K (by confidence)', 'type': 'text',
         'default': '', 'placeholder': 'empty = all'},
        {'name': 'dedupe', 'label': 'De-duplicate', 'type': 'select',
         'options': [
             {'value': 'off', 'label': 'Off'},
             {'value': 'nms', 'label': 'NMS (suppress overlaps)'},
             {'value': 'nmm', 'label': 'NMM (merge overlaps)'},
         ],
         'default': 'off'},
        {'name': 'dedupe_threshold', 'label': 'Overlap Threshold', 'type': 'text',
         'default': '0.5', 'placeholder': '0.5',
         'showIf': {'dedupe': ['nms', 'nmm']}},
        {'name': 'overlap_metric', 'label': 'Overlap Metric', 'type': 'select',
         'options': [
             {'value': 'iou', 'label': 'IoU (intersection over union)'},
             {'value': 'ios', 'label': 'IoS (intersection over smaller)'},
         ],
         'default': 'iou',
         'showIf': {'dedupe': ['nms', 'nmm']}},
        {'name': 'class_agnostic', 'label': 'Class-Agnostic De-dup', 'type': 'checkbox',
         'default': False,
         'showIf': {'dedupe': ['nms', 'nmm']}},
    ]

    def __init__(self, node_id=None, name="sv_filter"):
        self._missing_reported = False
        super().__init__(node_id, name)

    # ------------------------------------------------------------------
    # Criteria
    # ------------------------------------------------------------------

    def _criteria_mask(self, detections) -> np.ndarray:
        n = len(detections)
        mask = np.ones(n, dtype=bool)
        if n == 0:
            return mask

        conf = detections.confidence
        min_conf = _parse_float(self.config.get('min_confidence'))
        max_conf = _parse_float(self.config.get('max_confidence'))
        if conf is not None:
            if min_conf is not None:
                mask &= conf >= min_conf
            if max_conf is not None:
                mask &= conf <= max_conf

        allow = _parse_class_list(self.config.get('allow_classes'))
        deny = _parse_class_list(self.config.get('deny_classes'))
        if allow or deny:
            names = detections.data.get('class_name') if detections.data else None
            for i in range(n):
                tokens = set()
                if names is not None and i < len(names):
                    tokens.add(str(names[i]).lower())
                if detections.class_id is not None:
                    tokens.add(str(int(detections.class_id[i])))
                if allow and not (tokens & allow):
                    mask[i] = False
                if deny and (tokens & deny):
                    mask[i] = False

        widths = detections.xyxy[:, 2] - detections.xyxy[:, 0]
        heights = detections.xyxy[:, 3] - detections.xyxy[:, 1]

        min_area = _parse_float(self.config.get('min_area'))
        max_area = _parse_float(self.config.get('max_area'))
        if min_area is not None or max_area is not None:
            areas = widths * heights
            if min_area is not None:
                mask &= areas >= min_area
            if max_area is not None:
                mask &= areas <= max_area

        min_aspect = _parse_float(self.config.get('min_aspect'))
        max_aspect = _parse_float(self.config.get('max_aspect'))
        if min_aspect is not None or max_aspect is not None:
            with np.errstate(divide='ignore', invalid='ignore'):
                aspects = np.where(heights > 0, widths / np.maximum(heights, 1e-9), 0.0)
            if min_aspect is not None:
                mask &= aspects >= min_aspect
            if max_aspect is not None:
                mask &= aspects <= max_aspect

        top_k = _parse_float(self.config.get('top_k'))
        if top_k is not None and top_k >= 1 and conf is not None:
            passing = np.where(mask)[0]
            if len(passing) > int(top_k):
                order = passing[np.argsort(conf[passing])[::-1]]
                cut = set(order[int(top_k):].tolist())
                for i in cut:
                    mask[i] = False

        return mask

    def _dedupe(self, sv, detections):
        mode = self.config.get('dedupe', 'off')
        if mode not in ('nms', 'nmm') or len(detections) == 0:
            return detections

        threshold = _parse_float(self.config.get('dedupe_threshold'))
        threshold = 0.5 if threshold is None else threshold
        class_agnostic = self.get_config_bool('class_agnostic', False)
        metric = (sv.OverlapMetric.IOS
                  if str(self.config.get('overlap_metric', 'iou')).lower() == 'ios'
                  else sv.OverlapMetric.IOU)

        if mode == 'nms':
            return detections.with_nms(
                threshold=threshold, class_agnostic=class_agnostic,
                overlap_metric=metric)
        return detections.with_nmm(
            threshold=threshold, class_agnostic=class_agnostic,
            overlap_metric=metric)

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
        if not isinstance(payload, dict):
            self.send(msg)
            return

        try:
            detections = to_sv(payload)
            mask = self._criteria_mask(detections)

            kept = self._dedupe(sv, detections[mask])
            rejected = detections[~mask]

            # Split pattern (see ConfidenceFilterNode): both outputs always
            # fire; each message gets its own top-level dict and payload dict,
            # sharing the image (downstream nodes copy before mutating).
            kept_entries = sv_to_list(kept)
            rejected_entries = sv_to_list(rejected)

            rejected_msg = msg.copy()
            rejected_payload = payload.copy()
            rejected_msg[MessageKeys.PAYLOAD] = rejected_payload

            payload['sv'] = kept
            payload['detections'] = kept_entries
            payload['detection_count'] = len(kept_entries)

            rejected_payload['sv'] = rejected
            rejected_payload['detections'] = rejected_entries
            rejected_payload['detection_count'] = len(rejected_entries)

            self.send(rejected_msg, output_index=1)
            self.send(msg, output_index=0)

        except Exception as e:
            logger.error(f"Error in SupervisionFilterNode: {e}", exc_info=True)
            self.report_error(f"Filter error: {e}")
            self.send(msg)
