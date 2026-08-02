"""Shared helpers for nodes built on the ``supervision`` library.

``supervision`` lives in the ``[vision]`` extra, so it is absent from a core
install. Every node in the ``supervision`` category must therefore degrade
gracefully: report a clear error and pass the message through untouched rather
than raising at import time. :func:`import_supervision` centralises that.

Detections travel through a workflow in two parallel forms:

``payload['detections']``
    The interop format: a plain list of dicts (``bbox``, ``class_id``,
    ``class_name``, ``confidence``, optionally ``track_id``). Function, Debug,
    Switch, MQTT and every core node read this, so it must always be present.

``payload['sv']``
    Optional. The live :class:`supervision.Detections` object. Lossless - it
    carries masks, ``tracker_id`` and the ``data`` dict, none of which survive
    the dict round-trip. PyNode already passes raw numpy frames through
    ``payload['image']``, and ``BaseNode.send()`` only deep-copies on fan-out,
    so carrying a live object here is both established and cheap.

:func:`to_sv` prefers ``payload['sv']`` and falls back to rebuilding from the
dict list, so a supervision node works whether its upstream neighbour is
supervision-aware (UltralyticsNode emits dicts only) or not.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Key under which the live sv.Detections object rides in the payload.
SV_KEY = 'sv'

# Payload keys for the interop list form.
DETECTIONS_KEY = 'detections'
DETECTION_COUNT_KEY = 'detection_count'

_sv_module = None
_sv_import_error: Optional[str] = None


def import_supervision():
    """Import ``supervision`` once, returning ``None`` when unavailable.

    The result (module or failure) is cached, so a core install does not pay a
    failed import on every single frame.

    Returns:
        The ``supervision`` module, or ``None`` if it is not installed.
    """
    global _sv_module, _sv_import_error

    if _sv_module is not None:
        return _sv_module
    if _sv_import_error is not None:
        return None

    try:
        import supervision as sv  # type: ignore
        _sv_module = sv
        return sv
    except ImportError as e:
        _sv_import_error = str(e)
        return None


def supervision_missing_message() -> str:
    """Return the standard user-facing error for a missing supervision install."""
    return (
        "supervision library not installed. "
        'Run: pip install "pynode-flow[vision]"  (or: pip install supervision)'
    )


def _as_float_array(values: List[Any]) -> np.ndarray:
    return np.array(values, dtype=np.float32)


def to_sv(payload: Any):
    """Build an ``sv.Detections`` from a payload.

    Prefers the live object at ``payload['sv']`` (lossless). Falls back to
    rebuilding from ``payload['detections']``, carrying ``class_name`` through
    ``Detections.data`` so it survives operations that filter or reorder
    detections - notably ``ByteTrack.update_with_detections()``, which does
    both.

    Args:
        payload: The message payload (dict). Anything else yields an empty
            ``Detections``.

    Returns:
        An ``sv.Detections``, or ``None`` when supervision is not installed.
    """
    sv = import_supervision()
    if sv is None:
        return None

    if not isinstance(payload, dict):
        return sv.Detections.empty()

    existing = payload.get(SV_KEY)
    if isinstance(existing, sv.Detections):
        return existing

    detections_list = payload.get(DETECTIONS_KEY) or []
    if not isinstance(detections_list, (list, tuple)) or len(detections_list) == 0:
        return sv.Detections.empty()

    xyxy: List[Any] = []
    confidence: List[float] = []
    class_id: List[int] = []
    class_name: List[str] = []
    tracker_id: List[int] = []
    any_tracker_id = False

    for det in detections_list:
        if not isinstance(det, dict):
            continue
        bbox = det.get('bbox')
        if bbox is None or len(bbox) != 4:
            continue

        xyxy.append([float(v) for v in bbox])
        confidence.append(float(det.get('confidence', 0.0) or 0.0))
        class_id.append(int(det.get('class_id', 0) or 0))
        class_name.append(str(det.get('class_name', '') or ''))

        tid = det.get('track_id')
        if tid is None:
            # Placeholder so the array stays aligned with the other fields;
            # only used when at least one real id is present.
            tracker_id.append(-1)
        else:
            any_tracker_id = True
            tracker_id.append(int(tid))

    if not xyxy:
        return sv.Detections.empty()

    detections = sv.Detections(
        xyxy=_as_float_array(xyxy),
        confidence=_as_float_array(confidence),
        class_id=np.array(class_id, dtype=int),
        # class_name rides in `data` so supervision keeps it aligned through
        # filtering/reordering. Rebuilding a parallel Python list and indexing
        # it by output position silently mislabels objects.
        data={'class_name': np.array(class_name)},
    )

    if any_tracker_id:
        detections.tracker_id = np.array(tracker_id, dtype=int)

    return detections


def sv_to_list(detections) -> List[Dict[str, Any]]:
    """Flatten an ``sv.Detections`` into the interop list-of-dicts form.

    Every field is read positionally from the *same* ``Detections``, so class
    names and track ids stay attached to the box they belong to.

    Args:
        detections: An ``sv.Detections`` (or ``None``).

    Returns:
        A list of detection dicts. Empty when there is nothing to report.
    """
    if detections is None or len(detections) == 0:
        return []

    class_names = detections.data.get('class_name') if detections.data else None

    results: List[Dict[str, Any]] = []
    for i in range(len(detections)):
        bbox = [float(v) for v in detections.xyxy[i]]
        entry: Dict[str, Any] = {
            'bbox': bbox,
            'bbox_format': 'xyxy',
            'bbox_wh': [bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]],
            'class_id': (
                int(detections.class_id[i])
                if detections.class_id is not None else 0
            ),
            'confidence': (
                float(detections.confidence[i])
                if detections.confidence is not None else 0.0
            ),
        }

        if class_names is not None and i < len(class_names):
            entry['class_name'] = str(class_names[i])

        if detections.tracker_id is not None:
            entry['track_id'] = int(detections.tracker_id[i])

        if detections.mask is not None:
            entry['has_mask'] = True

        results.append(entry)

    return results


def write_back(detections, payload: Dict[str, Any],
               list_key: str = DETECTIONS_KEY,
               count_key: str = DETECTION_COUNT_KEY) -> List[Dict[str, Any]]:
    """Write ``detections`` into ``payload`` in both forms.

    Sets the live object at ``payload['sv']`` and the flattened list at
    ``payload[list_key]`` so supervision-aware and core nodes downstream both
    see the same result.

    Args:
        detections: An ``sv.Detections``.
        payload: The payload dict to update in place.
        list_key: Payload key for the list form.
        count_key: Payload key for the count.

    Returns:
        The list form that was written.
    """
    entries = sv_to_list(detections)

    payload[SV_KEY] = detections
    payload[list_key] = entries
    payload[count_key] = len(entries)

    return entries


def labels_for(detections, show_class: bool = True, show_confidence: bool = True,
               show_track_id: bool = True) -> List[str]:
    """Build per-detection label strings from a ``Detections``.

    Reads class names from ``data['class_name']`` rather than a caller-supplied
    parallel list, so labels cannot drift out of alignment with their boxes.

    Args:
        detections: An ``sv.Detections``.
        show_class: Include the class name (falls back to ``#<class_id>``).
        show_confidence: Include the confidence to two decimals.
        show_track_id: Include ``#<track_id>`` when tracker ids are present.

    Returns:
        One label string per detection.
    """
    if detections is None or len(detections) == 0:
        return []

    class_names = detections.data.get('class_name') if detections.data else None

    labels: List[str] = []
    for i in range(len(detections)):
        parts: List[str] = []

        if show_track_id and detections.tracker_id is not None:
            parts.append(f"#{int(detections.tracker_id[i])}")

        if show_class:
            if class_names is not None and i < len(class_names) and class_names[i]:
                parts.append(str(class_names[i]))
            elif detections.class_id is not None:
                parts.append(f"#{int(detections.class_id[i])}")

        if show_confidence and detections.confidence is not None:
            parts.append(f"{float(detections.confidence[i]):.2f}")

        labels.append(' '.join(parts))

    return labels


def resolve_position(name: str, default: str = 'CENTER'):
    """Resolve a ``sv.Position`` enum member by name.

    Args:
        name: Member name, e.g. ``'BOTTOM_CENTER'`` (case-insensitive).
        default: Member name to use when ``name`` is unknown.

    Returns:
        An ``sv.Position``, or ``None`` when supervision is not installed.
    """
    sv = import_supervision()
    if sv is None:
        return None

    key = str(name or default).strip().upper()
    return getattr(sv.Position, key, getattr(sv.Position, default))


def frame_size(image: Any) -> Tuple[int, int]:
    """Return ``(width, height)`` for a decoded frame, ``(0, 0)`` if unknown."""
    if image is None or not hasattr(image, 'shape') or len(image.shape) < 2:
        return (0, 0)
    return (int(image.shape[1]), int(image.shape[0]))


def parse_points(value: Any) -> Optional[List[List[float]]]:
    """Parse a polygon definition into ``[[x, y], ...]``.

    Accepts a JSON string (``"[[100,100],[300,100],...]"``), an already-parsed
    list of point pairs, or a flat comma string (``"100,100,300,100,..."``).
    The geometry editor writes the JSON form.

    Returns:
        The point list (>= 3 points), or ``None`` when unparseable.
    """
    import json

    points = None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            points = json.loads(text)
        except ValueError:
            try:
                flat = [float(p) for p in text.replace(';', ',').split(',') if p.strip()]
            except ValueError:
                return None
            if len(flat) < 6 or len(flat) % 2:
                return None
            points = [[flat[i], flat[i + 1]] for i in range(0, len(flat), 2)]
    elif isinstance(value, (list, tuple)):
        points = list(value)
    else:
        return None

    try:
        points = [[float(p[0]), float(p[1])] for p in points]
    except (TypeError, ValueError, IndexError):
        return None

    return points if len(points) >= 3 else None


def parse_line(value: Any) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    """Parse a line definition into ``((x1, y1), (x2, y2))``.

    Accepts ``"x1,y1,x2,y2"``, a JSON string ``"[[x1,y1],[x2,y2]]"``, or an
    already-parsed pair of points.

    Returns:
        The two endpoints, or ``None`` when unparseable.
    """
    import json

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith('['):
            try:
                value = json.loads(text)
            except ValueError:
                return None
        else:
            try:
                flat = [float(p) for p in text.split(',') if p.strip()]
            except ValueError:
                return None
            if len(flat) != 4:
                return None
            return ((flat[0], flat[1]), (flat[2], flat[3]))

    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return ((float(value[0][0]), float(value[0][1])),
                    (float(value[1][0]), float(value[1][1])))
        except (TypeError, ValueError, IndexError):
            return None

    return None
