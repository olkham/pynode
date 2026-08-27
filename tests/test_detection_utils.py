"""Tests for the detection interop helpers and the DrawPredictionsNode that
consumes them.

The regression these cover: the ONNX engine reports centre-based boxes under
``top_class``/``top_score`` while InferenceNode advertised ``bbox_format:
xyxy``, so DrawPredictionsNode drew every ONNX box at the wrong place and size.

Nodes are driven directly (no Flask app / workflows dir); the node is wired to
the conftest 'sink' (synchronous on_input_direct delivery).
"""

import base64

import cv2
import numpy as np
import pytest

from pynode.nodes.detection_utils import (
    CANONICAL_BBOX_FORMAT,
    normalized_detection,
    normalized_detections,
    to_xyxy,
)
from pynode.nodes.DrawPredictionsNode.draw_predictions_node import DrawPredictionsNode


# --- to_xyxy: every spelling describes the SAME box -> [100, 200, 300, 400] ---

@pytest.mark.parametrize('fmt,bbox', [
    ('xyxy', [100, 200, 300, 400]),
    ('x1y1x2y2', [100, 200, 300, 400]),
    ('ltrb', [100, 200, 300, 400]),
    ('cxcywh', [200, 300, 200, 200]),
    ('xywh_center', [200, 300, 200, 200]),
    ('yolo', [200, 300, 200, 200]),
    ('xywh', [100, 200, 200, 200]),
    ('ltwh', [100, 200, 200, 200]),
    ('coco', [100, 200, 200, 200]),
])
def test_to_xyxy_formats(fmt, bbox):
    assert to_xyxy(bbox, fmt) == [100.0, 200.0, 300.0, 400.0]


def test_to_xyxy_unknown_format_assumes_corners():
    assert to_xyxy([1, 2, 3, 4], 'something-else') == [1.0, 2.0, 3.0, 4.0]


def test_to_xyxy_case_and_whitespace_insensitive():
    assert to_xyxy([200, 300, 200, 200], ' CxCyWH ') == [100.0, 200.0, 300.0, 400.0]


def test_to_xyxy_ignores_trailing_values():
    assert to_xyxy([100, 200, 300, 400, 0.9], 'xyxy') == [100.0, 200.0, 300.0, 400.0]


def test_to_xyxy_rejects_short_box():
    with pytest.raises(ValueError):
        to_xyxy([1, 2, 3], 'xyxy')


# --- normalized_detection ---

def _onnx_detection():
    """What OnnxEngine._postprocess actually emits."""
    return {
        'bbox': [200.0, 300.0, 200.0, 200.0],
        'bbox_format': 'xywh_center',
        'class_confidences': [0.01, 0.02, 0.93],
        'top_class': 2,
        'top_score': 0.93,
        'detection_index': 0,
    }


def test_normalizes_onnx_detection():
    out = normalized_detection(_onnx_detection())

    assert out['bbox'] == [100.0, 200.0, 300.0, 400.0]
    assert out['bbox_format'] == CANONICAL_BBOX_FORMAT
    assert out['class_id'] == 2
    assert out['class_name'] == '2'
    assert out['confidence'] == pytest.approx(0.93)


def test_preserves_engine_specific_keys():
    out = normalized_detection(_onnx_detection())

    assert out['class_confidences'] == [0.01, 0.02, 0.93]
    assert out['detection_index'] == 0
    assert out['top_class'] == 2  # the engine's own keys still ride along


def test_does_not_mutate_input():
    det = _onnx_detection()
    normalized_detection(det)

    assert det['bbox'] == [200.0, 300.0, 200.0, 200.0]
    assert det['bbox_format'] == 'xywh_center'


def test_canonical_detection_passes_through():
    det = {
        'bbox': [100, 200, 300, 400],
        'bbox_format': 'xyxy',
        'class_id': 3,
        'class_name': 'person',
        'confidence': 0.8,
        'track_id': 7,
    }
    out = normalized_detection(det)

    assert out['bbox'] == [100.0, 200.0, 300.0, 400.0]
    assert (out['class_id'], out['class_name']) == (3, 'person')
    assert out['confidence'] == pytest.approx(0.8)
    assert out['track_id'] == 7


def test_detection_format_overrides_payload_default():
    det = {'bbox': [200, 300, 200, 200], 'bbox_format': 'cxcywh'}
    out = normalized_detection(det, default_format='xyxy')

    assert out['bbox'] == [100.0, 200.0, 300.0, 400.0]


def test_payload_default_used_when_detection_is_unlabelled():
    det = {'bbox': [200, 300, 200, 200]}
    out = normalized_detection(det, default_format='cxcywh')

    assert out['bbox'] == [100.0, 200.0, 300.0, 400.0]


def test_cat_map_class_name_becomes_the_label():
    """OnnxEngine puts a category *name* in top_class when given a cat_map."""
    out = normalized_detection({'bbox': [0, 0, 10, 10], 'top_class': 'crack', 'top_score': 0.5})

    assert out['class_name'] == 'crack'
    assert out['class_id'] == 0  # no numeric id available


def test_numpy_bbox_is_converted():
    out = normalized_detection({'bbox': np.array([200, 300, 200, 200]), 'bbox_format': 'cxcywh'})

    assert out['bbox'] == [100.0, 200.0, 300.0, 400.0]


def test_missing_class_and_confidence_get_defaults():
    out = normalized_detection({'bbox': [1, 2, 3, 4]})

    assert out['class_id'] == 0
    assert out['class_name'] == 'unknown'
    assert out['confidence'] == 0.0


def test_track_id_alias():
    out = normalized_detection({'bbox': [1, 2, 3, 4], 'tracker_id': 5})

    assert out['track_id'] == 5


def test_detection_without_bbox_is_left_alone():
    out = normalized_detection({'class_id': 1, 'confidence': 0.4})

    assert 'bbox' not in out
    assert out['class_id'] == 1


def test_normalized_detections_skips_malformed_entries():
    out = normalized_detections([
        {'bbox': [200, 300, 200, 200], 'bbox_format': 'cxcywh'},
        'not-a-detection',
        {'bbox': [1, 2]},  # too short
        {'bbox': [10, 20, 30, 40]},
    ])

    assert [d['bbox'] for d in out] == [[100.0, 200.0, 300.0, 400.0], [10.0, 20.0, 30.0, 40.0]]


def test_normalized_detections_handles_non_list():
    assert normalized_detections(None) == []


# --- DrawPredictionsNode: the box actually lands where it should ---

def _img_payload(h=480, w=640):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    ok, buf = cv2.imencode('.jpg', img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode('utf-8')


def _drawn(sink, payload):
    node = DrawPredictionsNode(name='draw')
    node.configure({'line_width': '2', 'show_class': 'false', 'show_confidence': 'false'})
    node.connect(sink)
    node.on_input({'payload': payload})

    out = sink.received[-1]['payload']
    data = base64.b64decode(out['image'])
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def _box_bounds(img):
    """Bounding box of everything drawn on an all-black frame.

    Uses the brightest channel (a pure-blue box is dark in grayscale) with a
    threshold, because the payload round-trips through JPEG and its ringing
    leaves faint non-zero pixels either side of a drawn line.
    """
    ys, xs = np.nonzero(img.max(axis=2) > 80)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def test_draws_onnx_centre_boxes_in_the_right_place(node_classes):
    """The reported bug: centre-based boxes drawn as if they were corners."""
    sink = node_classes['sink'](name='sink')
    img = _drawn(sink, {
        'image': _img_payload(),
        'detections': [_onnx_detection()],
        'bbox_format': 'xyxy',  # what InferenceNode used to claim regardless
    })

    x1, y1, x2, y2 = _box_bounds(img)
    # [cx=200, cy=300, w=200, h=200] -> corners (100,200)-(300,400), give or
    # take the line width straddling the edge.
    assert (x1, y1, x2, y2) == pytest.approx((100, 200, 300, 400), abs=2)


def test_draws_xyxy_boxes_unchanged(node_classes):
    sink = node_classes['sink'](name='sink')
    img = _drawn(sink, {
        'image': _img_payload(),
        'detections': [{'bbox': [100, 200, 300, 400], 'bbox_format': 'xyxy', 'class_id': 1}],
    })

    assert _box_bounds(img) == pytest.approx((100, 200, 300, 400), abs=2)


def test_payload_level_format_applies_to_unlabelled_detections(node_classes):
    sink = node_classes['sink'](name='sink')
    img = _drawn(sink, {
        'image': _img_payload(),
        'detections': [{'bbox': [200, 300, 200, 200], 'class_id': 0}],
        'bbox_format': 'cxcywh',
    })

    assert _box_bounds(img) == pytest.approx((100, 200, 300, 400), abs=2)


def test_onnx_labels_use_top_class_and_top_score(node_classes):
    """Labels used to read 'unknown (0.00)' for ONNX detections."""
    sink = node_classes['sink'](name='sink')
    node = DrawPredictionsNode(name='draw')
    node.connect(sink)

    captured = {}
    original = cv2.putText

    def spy(img, text, *args, **kwargs):
        captured['text'] = text
        return original(img, text, *args, **kwargs)

    cv2.putText = spy
    try:
        node.on_input({'payload': {'image': _img_payload(), 'detections': [_onnx_detection()]}})
    finally:
        cv2.putText = original

    assert captured['text'] == '2 (0.93)'
