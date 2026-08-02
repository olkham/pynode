"""Tests for SupervisionAnnotateNode.

Driven directly via ``on_input`` wired to the conftest 'sink' - no Flask app,
no workflows dir, no worker threads, nothing touching real workflow data.
"""

import numpy as np
import pytest

sv = pytest.importorskip('supervision')

from pynode.nodes.Supervision.supervision_annotate_node import (  # noqa: E402
    ANNOTATOR_ORDER,
    SupervisionAnnotateNode,
)


def _img(h=240, w=320):
    """A textured frame - blur/pixelate on a uniform image is a no-op."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


def _dets(track_id=None):
    d = {'bbox': [40, 40, 120, 200], 'class_id': 0, 'class_name': 'person',
         'confidence': 0.92}
    if track_id is not None:
        d['track_id'] = track_id
    return [d]


def _make(sink, **config):
    node = SupervisionAnnotateNode(name='sv_annotate')
    if config:
        node.configure(config)
    node.connect(sink)
    return node


def _run(sink, node, payload):
    node.on_input({'payload': payload})
    return sink.received[-1]['payload'] if sink.received else None


# --- basic drawing -------------------------------------------------------

def test_box_and_label_annotate_the_frame(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['box', 'label'])

    image = _img()
    out = _run(sink, node, {'image': image, 'detections': _dets()})

    assert out['image'].shape == image.shape
    assert (out['image'] != image).any()          # something was drawn
    assert (node._built_style is not None)


def test_input_frame_is_not_mutated(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['box'])

    image = _img()
    original = image.copy()
    _run(sink, node, {'image': image, 'detections': _dets()})

    assert (image == original).all()


def test_blur_modifies_only_the_bbox_region(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['blur'])

    image = _img()
    out = _run(sink, node, {'image': image, 'detections': _dets()})

    inside = (out['image'][50:190, 50:110] != image[50:190, 50:110]).any()
    outside = (out['image'][:30, :] != image[:30, :]).any()
    assert inside and not outside


def test_every_catalogued_annotator_runs(node_classes):
    """Each option must construct and annotate without raising."""
    sink = node_classes['sink'](name='sink')
    for name in ANNOTATOR_ORDER:
        node = _make(sink, annotators=[name])
        out = _run(sink, node, {'image': _img(), 'detections': _dets(track_id=1)})
        assert out is not None, name


def test_selection_order_does_not_matter(node_classes):
    """Whatever order the boxes are ticked, application order is canonical."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['label', 'blur', 'box'])
    assert node._selected() == ['blur', 'box', 'label']


# --- trace / tracker interplay -------------------------------------------

def test_trace_draws_after_two_frames_with_track_ids(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['trace'])

    base = np.full((240, 320, 3), 30, np.uint8)
    _run(sink, node, {'image': base.copy(),
                      'detections': [{'bbox': [40, 40, 120, 200], 'class_id': 0,
                                      'class_name': 'person', 'confidence': 0.9,
                                      'track_id': 1}]})
    out = _run(sink, node, {'image': base.copy(),
                            'detections': [{'bbox': [80, 40, 160, 200], 'class_id': 0,
                                            'class_name': 'person', 'confidence': 0.9,
                                            'track_id': 1}]})

    assert (out['image'] != 30).any(axis=2).sum() > 0  # the trace line


def test_trace_without_track_ids_is_skipped_not_fatal(node_classes):
    """TraceAnnotator raises on missing tracker_id; the node must not."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['trace', 'box'])

    errors = []
    node.report_error = lambda m: errors.append(m)

    image = _img()
    out = _run(sink, node, {'image': image, 'detections': _dets()})       # no track_id
    _run(sink, node, {'image': _img(), 'detections': _dets()})

    assert (out['image'] != image).any()      # box still drew
    assert len(errors) == 1                   # warned once, not per frame
    assert 'Tracker' in errors[0]


def test_trace_skips_empty_frames(node_classes):
    """Empty Detections also lack tracker_id - must not raise or warn."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['trace'])

    errors = []
    node.report_error = lambda m: errors.append(m)

    out = _run(sink, node, {'image': _img(), 'detections': []})

    assert out is not None and not errors


def test_track_color_lookup_falls_back_without_track_ids(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['box'], color_lookup='track')

    image = _img()
    out = _run(sink, node, {'image': image, 'detections': _dets()})  # no ids

    assert (out['image'] != image).any()  # drew via CLASS fallback, no raise

    out = _run(sink, node, {'image': _img(), 'detections': _dets(track_id=3)})
    assert out is not None                # and TRACK works when ids appear


# --- state management -----------------------------------------------------

def test_annotators_are_cached_across_frames(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['box', 'trace'])

    _run(sink, node, {'image': _img(), 'detections': _dets(track_id=1)})
    first = dict(node._annotators)
    _run(sink, node, {'image': _img(), 'detections': _dets(track_id=1)})

    assert node._annotators['box'] is first['box']
    assert node._annotators['trace'] is first['trace']


def test_style_change_rebuilds_annotators(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['box'], thickness='2')

    _run(sink, node, {'image': _img(), 'detections': _dets()})
    first = node._annotators['box']

    node.configure({'thickness': '5'})
    _run(sink, node, {'image': _img(), 'detections': _dets()})

    assert node._annotators['box'] is not first
    assert node._annotators['box'].thickness == 5


def test_reset_clears_only_stateful_annotators(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['box', 'trace', 'heatmap'])

    _run(sink, node, {'image': _img(), 'detections': _dets(track_id=1)})
    box = node._annotators['box']

    node.reset()

    assert 'trace' not in node._annotators
    assert 'heatmap' not in node._annotators
    assert node._annotators['box'] is box


def test_reset_is_a_declared_action():
    assert 'reset' in SupervisionAnnotateNode.actions


def test_auto_thickness_scales_with_resolution(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['box'], thickness='auto')

    _run(sink, node, {'image': _img(h=240, w=320), 'detections': _dets()})
    small = node._annotators['box'].thickness
    _run(sink, node, {'image': _img(h=1080, w=1920), 'detections': _dets()})
    large = node._annotators['box'].thickness

    assert large > small


# --- robustness ----------------------------------------------------------

def test_no_image_passes_through(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    node.on_input({'payload': {'detections': _dets()}})

    assert sink.received[-1]['payload']['detections'] == _dets()


def test_empty_detections_pass_frame_through(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, annotators=['box', 'label', 'heatmap'])

    image = _img()
    out = _run(sink, node, {'image': image, 'detections': []})

    assert out['image'].shape == image.shape


def test_degrades_gracefully_without_supervision(node_classes, monkeypatch):
    import pynode.nodes.Supervision.supervision_annotate_node as mod

    monkeypatch.setattr(mod, 'import_supervision', lambda: None)

    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    errors = []
    monkeypatch.setattr(node, 'report_error', lambda m: errors.append(m))

    node.on_input({'payload': {'image': _img(), 'detections': _dets()}})
    node.on_input({'payload': {'image': _img(), 'detections': _dets()}})

    assert len(sink.received) == 2
    assert len(errors) == 1
    assert 'supervision' in errors[0].lower()


def test_node_registers_in_supervision_category():
    assert SupervisionAnnotateNode.category == 'supervision'
