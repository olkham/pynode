"""
Class Map Node - relabels detections by class id or class name.

A model reports whatever it was trained with, and often not much: an ONNX model
carries no label file, so its detections arrive as ``class_id: 2`` /
``class_name: "2"``. This node applies a mapping of your own - ``2 = drone`` -
to every detection in the list, leaving boxes, scores and every other field
untouched.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pynode.nodes.base_node import BaseNode, Info, MessageKeys

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text(
    "Renames detection classes. Give it a mapping from class id (or existing "
    "class name) to the label you want, and every detection in the list is "
    "relabelled - useful for models that report bare numeric classes."
)
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with a detections list (e.g. from Inference or a tracker)"),
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "The same message with class_name rewritten on each detection"),
)
_info.add_header("Mapping")
_info.add_text("One entry per line, key first:")
_info.add_code("2 = drone").text(
    "- a colon, arrow or comma works as the separator too, quotes are "
    "optional, and lines starting with # are ignored."
).end()
_info.add_code('{"1": "bird", "2": "drone"}').text("A JSON object works too.").end()
_info.add_header("Options")
_info.add_bullets(
    ("Match On:", "Look the key up against the class id, the class name, or either"),
    ("Unmatched:", "Leave a detection's label alone, replace it with a fallback, or drop it"),
    ("Detections Path:", "Where the list lives (payload.detections, payload.tracks, ...)"),
)

# Key/value separators accepted in the line form, longest first so that '->'
# is not read as '-' followed by '>'.
_ENTRY_SEPARATOR = re.compile(r'\s*(?:=>|->|=|:|\t|,)\s*')


def _unquote(text: str) -> str:
    """Strip surrounding whitespace and one layer of matching quotes."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1]
    return text.strip()


def parse_class_map(raw: Any) -> Tuple[Dict[str, str], List[str]]:
    """Parse the mapping config into ``{key: label}``.

    Accepts a dict (already parsed by the UI), a JSON object, or one entry per
    line in any of the ``2 = drone`` / ``2: drone`` / ``2 -> drone`` /
    ``2, drone`` spellings.

    Args:
        raw: The raw config value.

    Returns:
        ``(mapping, problems)`` - ``problems`` lists the lines that could not
        be read, so the caller can report them once instead of per frame.
    """
    if isinstance(raw, dict):
        return {str(k).strip(): str(v) for k, v in raw.items()}, []

    text = str(raw or '').strip()
    if not text:
        return {}, []

    if text.startswith('{'):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            return {}, [f"invalid JSON ({e.msg} at line {e.lineno})"]
        if isinstance(data, dict):
            return {str(k).strip(): str(v) for k, v in data.items()}, []
        return {}, ["JSON mapping must be an object"]

    mapping: Dict[str, str] = {}
    problems: List[str] = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = _ENTRY_SEPARATOR.split(line, maxsplit=1)
        if len(parts) != 2:
            problems.append(line)
            continue

        key, value = _unquote(parts[0]), _unquote(parts[1])
        if not key or not value:
            problems.append(line)
            continue

        mapping[key] = value

    return mapping, problems


class ClassMapNode(BaseNode):
    """Rewrites ``class_name`` on every detection from a user-supplied map."""

    display_name = 'Class Map'
    info = str(_info)
    icon = '🔤'
    category = 'vision'
    color = '#C7E9C0'
    border_color = '#74C476'
    text_color = '#000000'
    input_count = 1
    output_count = 1

    DEFAULT_CONFIG = {
        'mapping': '',
        'match_on': 'either',
        'unmatched': 'keep',
        'unmatched_label': 'unknown',
        'detections_path': 'payload.detections',
    }

    properties = [
        {
            'name': 'mapping',
            'label': 'Class Mapping',
            'type': 'textarea',
            'default': DEFAULT_CONFIG['mapping'],
            'placeholder': '2 = drone\n1 = bird',
            'help': 'One "id = label" per line, or a JSON object. Lines starting with # are ignored.'
        },
        {
            'name': 'match_on',
            'label': 'Match On',
            'type': 'select',
            'options': [
                {'value': 'either', 'label': 'Class ID, then class name'},
                {'value': 'class_id', 'label': 'Class ID only'},
                {'value': 'class_name', 'label': 'Class name only'},
            ],
            'default': DEFAULT_CONFIG['match_on'],
            'help': 'What the mapping keys are matched against. Name matching ignores case.'
        },
        {
            'name': 'unmatched',
            'label': 'Unmatched Detections',
            'type': 'select',
            'options': [
                {'value': 'keep', 'label': 'Keep their current label'},
                {'value': 'label', 'label': 'Relabel with a fallback'},
                {'value': 'drop', 'label': 'Drop the detection'},
            ],
            'default': DEFAULT_CONFIG['unmatched'],
            'help': 'What to do with a detection whose class is not in the mapping'
        },
        {
            'name': 'unmatched_label',
            'label': 'Fallback Label',
            'type': 'text',
            'default': DEFAULT_CONFIG['unmatched_label'],
            'showIf': {'unmatched': 'label'},
            'help': 'Label given to detections that the mapping does not cover'
        },
        {
            'name': 'detections_path',
            'label': 'Detections Path',
            'type': 'text',
            'default': DEFAULT_CONFIG['detections_path'],
            'help': f'Path to the detections list (e.g. "{DEFAULT_CONFIG["detections_path"]}")'
        },
    ]

    def __init__(self, node_id=None, name="class map"):
        super().__init__(node_id, name)
        # Parsing is cached against the raw config value: the map is re-read
        # when the user edits it, not once per frame.
        self._cached_raw: Any = None
        self._cached_map: Dict[str, str] = {}
        self._cached_lower: Dict[str, str] = {}

    def _mapping(self) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Return ``(mapping, lowercased mapping)``, re-parsing only on change."""
        raw = self.config.get('mapping', self.DEFAULT_CONFIG['mapping'])

        if raw != self._cached_raw or (raw and not self._cached_map):
            mapping, problems = parse_class_map(raw)
            self._cached_raw = raw
            self._cached_map = mapping
            self._cached_lower = {k.lower(): v for k, v in mapping.items()}
            if problems:
                self.report_error(
                    "Could not read class mapping entries: " + '; '.join(problems)
                )

        return self._cached_map, self._cached_lower

    def _lookup(self, det: Dict[str, Any], mapping: Dict[str, str],
                lower: Dict[str, str], match_on: str) -> Optional[str]:
        """Find the mapped label for one detection, or None when unmapped."""
        if match_on in ('class_id', 'either'):
            class_id = det.get(MessageKeys.CV.CLASS_ID)
            if class_id is not None:
                label = mapping.get(str(class_id).strip())
                if label is not None:
                    return label

        if match_on in ('class_name', 'either'):
            class_name = det.get(MessageKeys.CV.CLASS_NAME)
            if class_name is not None:
                label = lower.get(str(class_name).strip().lower())
                if label is not None:
                    return label

        return None

    def _sync_supervision(self, payload: Dict[str, Any],
                          detections: List[Any], kept: List[bool]) -> None:
        """Mirror the new labels onto a live ``sv.Detections`` in the payload.

        Supervision nodes prefer ``payload['sv']`` over the dict list, so an
        annotator downstream would otherwise keep drawing the old names.
        """
        sv_detections = payload.get('sv')
        if sv_detections is None or not hasattr(sv_detections, 'xyxy'):
            return

        try:
            import numpy as np

            if len(kept) != len(sv_detections):
                # The list came from somewhere else; leave sv alone rather than
                # pairing labels with the wrong boxes.
                return

            if not all(kept):
                sv_detections = sv_detections[np.array(kept, dtype=bool)]
                payload['sv'] = sv_detections

            names = [
                str(det.get(MessageKeys.CV.CLASS_NAME, ''))
                for det in detections if isinstance(det, dict)
            ]
            if len(names) == len(sv_detections) and isinstance(sv_detections.data, dict):
                sv_detections.data['class_name'] = np.array(names)

        except Exception as e:
            logger.debug(f"Could not sync class names onto payload['sv']: {e}")

    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Relabel every detection at the configured path."""
        mapping, lower = self._mapping()
        unmatched = self.config.get('unmatched', self.DEFAULT_CONFIG['unmatched'])

        if not mapping and unmatched != 'drop':
            # Nothing configured yet - a pass-through beats an error on a node
            # the user has only just dropped onto the canvas.
            self.send(msg)
            return

        path = self.config.get('detections_path', self.DEFAULT_CONFIG['detections_path'])
        detections = self._get_nested_value(msg, path)
        if not isinstance(detections, (list, tuple)):
            self.send(msg)
            return

        match_on = self.config.get('match_on', self.DEFAULT_CONFIG['match_on'])
        fallback = self.config.get('unmatched_label', self.DEFAULT_CONFIG['unmatched_label'])

        out: List[Any] = []
        kept: List[bool] = []
        changed = False

        for det in detections:
            if not isinstance(det, dict):
                out.append(det)
                kept.append(True)
                continue

            label = self._lookup(det, mapping, lower, match_on)

            if label is None:
                if unmatched == 'drop':
                    kept.append(False)
                    changed = True
                    continue
                if unmatched == 'label':
                    label = fallback
                else:
                    out.append(det)
                    kept.append(True)
                    continue

            if det.get(MessageKeys.CV.CLASS_NAME) != label:
                # Copy rather than mutate: the same detection dict may still be
                # referenced by a message that branched upstream of this node.
                det = dict(det)
                det[MessageKeys.CV.CLASS_NAME] = label
                changed = True

            out.append(det)
            kept.append(True)

        if not changed:
            self.send(msg)
            return

        self._set_nested_value(msg, path, out)

        payload = msg.get(MessageKeys.PAYLOAD)
        if isinstance(payload, dict):
            # Only when the list we just wrote IS the payload's detections -
            # a node pointed at payload.tracks must not touch detection_count.
            if payload.get(MessageKeys.CV.DETECTIONS) is out:
                payload[MessageKeys.CV.DETECTION_COUNT] = len(out)
            self._sync_supervision(payload, out, kept)

        self.send(msg)
