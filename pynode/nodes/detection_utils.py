"""Shared helpers for the interop detection format.

Detections travel between vision nodes as ``payload['detections']``: a list of
dicts keyed ``bbox`` / ``class_id`` / ``class_name`` / ``confidence``, with the
box in ``xyxy`` pixel coordinates (see :mod:`pynode.nodes.supervision_utils`).

Inference engines do not all speak that dialect natively. The ONNX engine
reports centre-based boxes under ``top_class`` / ``top_score``, Ultralytics
reports ``xyxy`` under ``class_id`` / ``confidence``, and a FunctionNode may
hand-build either. A consumer that reads the canonical keys directly therefore
draws ONNX boxes at the wrong place and size, and labels them ``unknown``.

:func:`normalized_detection` maps any of those onto the canonical form. The
engine's own keys are preserved, so nothing downstream loses information.

Bounding box vocabulary (shared with the ``bbox_format`` selectors on CropNode,
BBoxMetricsNode and the coordinate nodes):

``xyxy``
    ``[x1, y1, x2, y2]`` - two corners. The canonical form.
``cxcywh``
    ``[cx, cy, w, h]`` - centre plus size, what the YOLO family emits.
    ``xywh_center`` and ``yolo`` are accepted spellings of the same thing.
``xywh``
    ``[x, y, w, h]`` - top-left corner plus size, the COCO reading.
    ``ltwh``, ``tlwh`` and ``coco`` are accepted spellings of the same thing.

Coordinates are passed through as-is: a normalized (0-1) box stays normalized.
Use DenormalizeCoordsNode when a producer emits normalized boxes.
"""

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pynode.nodes.messages import MessageKeys

logger = logging.getLogger(__name__)

# The format every consumer can assume once a detection has been normalized.
CANONICAL_BBOX_FORMAT = 'xyxy'

_CORNER_FORMATS = frozenset({'xyxy', 'x1y1x2y2', 'ltrb', 'pascal_voc'})
_CENTER_FORMATS = frozenset({'cxcywh', 'xywh_center', 'ccwh', 'yolo'})
_TOP_LEFT_FORMATS = frozenset({'xywh', 'ltwh', 'tlwh', 'coco', 'xywh_topleft'})

# Aliases accepted for the canonical detection keys, most preferred first.
_CLASS_ID_KEYS = (MessageKeys.CV.CLASS_ID, 'top_class', 'cls', 'class')
_CLASS_NAME_KEYS = (MessageKeys.CV.CLASS_NAME, 'label', 'name')
_CONFIDENCE_KEYS = (MessageKeys.CV.CONFIDENCE, 'top_score', 'score', 'conf')
_TRACK_ID_KEYS = (MessageKeys.CV.TRACK_ID, 'tracker_id')


def _first(det: Dict[str, Any], keys: Sequence[str]) -> Optional[Any]:
    """Return the first key present and non-None in ``det``."""
    for key in keys:
        value = det.get(key)
        if value is not None:
            return value
    return None


def to_xyxy(bbox: Iterable[Any],
            bbox_format: str = CANONICAL_BBOX_FORMAT) -> List[float]:
    """Convert a 4-value box to ``[x1, y1, x2, y2]``.

    Args:
        bbox: The box values. Only the first four are read, so a detection
            carrying extra trailing values still converts.
        bbox_format: One of the spellings listed in the module docstring.
            An unrecognised format is treated as ``xyxy`` (logged at debug),
            which is what an unlabelled detection almost always is.

    Returns:
        The box as four floats in ``xyxy`` order.

    Raises:
        ValueError: If fewer than four values are given.
        TypeError: If a value is not numeric.
    """
    values = [float(v) for v in list(bbox)[:4]]
    if len(values) != 4:
        raise ValueError(f"bbox needs 4 values, got {len(values)}")

    fmt = str(bbox_format or CANONICAL_BBOX_FORMAT).strip().lower()
    a, b, c, d = values

    if fmt in _CENTER_FORMATS:
        return [a - c / 2, b - d / 2, a + c / 2, b + d / 2]
    if fmt in _TOP_LEFT_FORMATS:
        return [a, b, a + c, b + d]
    if fmt not in _CORNER_FORMATS:
        logger.debug(f"Unknown bbox_format '{bbox_format}', assuming xyxy")
    return values


def _resolve_class(det: Dict[str, Any]) -> Tuple[int, str]:
    """Pull ``(class_id, class_name)`` out of a detection.

    Handles the ONNX engine's ``top_class``, which is an int index normally but
    a category *name* when the engine was given a ``cat_map``.
    """
    raw_id = _first(det, _CLASS_ID_KEYS)
    name = _first(det, _CLASS_NAME_KEYS)

    class_id = 0
    if raw_id is not None:
        try:
            class_id = int(raw_id)
        except (TypeError, ValueError):
            # A non-numeric id is a category name (ONNX cat_map).
            if name is None:
                name = str(raw_id)

    if name is None:
        # Match the engines: an unnamed class is labelled by its index.
        name = str(class_id) if raw_id is not None else 'unknown'

    return class_id, str(name)


def normalized_detection(det: Dict[str, Any],
                         default_format: str = CANONICAL_BBOX_FORMAT) -> Dict[str, Any]:
    """Return a copy of ``det`` in the canonical interop form.

    The box is converted to ``xyxy`` and the class/confidence/track keys are
    filled in from whichever alias the producer used. Every original key is
    kept, so engine extras (``class_confidences``, ``detection_index``, masks)
    survive.

    Args:
        det: A single detection dict.
        default_format: Format to assume when the detection carries no
            ``bbox_format`` of its own - pass the payload-level
            ``bbox_format`` here.

    Returns:
        A new dict; ``det`` is not modified.

    Raises:
        TypeError: If ``det`` is not a dict.
    """
    if not isinstance(det, dict):
        raise TypeError(f"detection must be a dict, got {type(det).__name__}")

    out = dict(det)

    bbox = det.get(MessageKeys.CV.BBOX)
    if bbox is not None:
        fmt = det.get(MessageKeys.CV.BBOX_FORMAT) or default_format
        if hasattr(bbox, 'tolist'):  # numpy array
            bbox = bbox.tolist()
        out[MessageKeys.CV.BBOX] = to_xyxy(bbox, fmt)
        out[MessageKeys.CV.BBOX_FORMAT] = CANONICAL_BBOX_FORMAT

    class_id, class_name = _resolve_class(det)
    out[MessageKeys.CV.CLASS_ID] = class_id
    out[MessageKeys.CV.CLASS_NAME] = class_name

    confidence = _first(det, _CONFIDENCE_KEYS)
    try:
        out[MessageKeys.CV.CONFIDENCE] = float(confidence) if confidence is not None else 0.0
    except (TypeError, ValueError):
        out[MessageKeys.CV.CONFIDENCE] = 0.0

    track_id = _first(det, _TRACK_ID_KEYS)
    if track_id is not None:
        out[MessageKeys.CV.TRACK_ID] = track_id

    return out


def normalized_detections(detections: Any,
                          default_format: str = CANONICAL_BBOX_FORMAT) -> List[Dict[str, Any]]:
    """Normalize a whole detection list, skipping entries that cannot convert.

    One malformed detection should not cost the caller the rest of the frame,
    so failures are logged at debug and dropped.

    Args:
        detections: The detection list (anything non-iterable yields ``[]``).
        default_format: Format assumed for detections without their own
            ``bbox_format``.

    Returns:
        A list of canonical detection dicts.
    """
    if not isinstance(detections, (list, tuple)):
        if detections is None or not hasattr(detections, '__iter__'):
            return []
        detections = list(detections)

    out: List[Dict[str, Any]] = []
    for i, det in enumerate(detections):
        try:
            out.append(normalized_detection(det, default_format))
        except (TypeError, ValueError) as e:
            logger.debug(f"Skipping detection {i}: {e}")

    return out


__all__ = [
    'CANONICAL_BBOX_FORMAT',
    'normalized_detection',
    'normalized_detections',
    'to_xyxy',
]
