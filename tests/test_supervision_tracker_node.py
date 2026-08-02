"""Tests for SupervisionTrackerNode.

The node is driven directly via ``on_input`` and wired to the conftest 'sink'
(synchronous ``on_input_direct`` delivery) - no Flask app, no workflows dir, no
worker threads started, so nothing here can touch real workflow data.

The tracker does not draw - visualisation lives in SupervisionAnnotateNode.
"""

import numpy as np
import pytest

pytest.importorskip('supervision')

from pynode.nodes.Supervision.supervision_tracker_node import (  # noqa: E402
    SupervisionTrackerNode,
)
from pynode.nodes.supervision_utils import SV_KEY  # noqa: E402


def _make(sink, **config):
    node = SupervisionTrackerNode(name='sv_tracker')
    if config:
        node.configure(config)
    node.connect(sink)
    return node


def _run(sink, node, payload):
    node.on_input({'payload': payload})
    return sink.received[-1]['payload'] if sink.received else None


def _person(bbox=(200, 20, 260, 140), conf=0.95):
    return {'bbox': list(bbox), 'class_id': 0, 'class_name': 'person', 'confidence': conf}


def _car(bbox=(10, 10, 50, 90), conf=0.30):
    return {'bbox': list(bbox), 'class_id': 2, 'class_name': 'car', 'confidence': conf}


# --- core behaviour ------------------------------------------------------

def test_assigns_track_ids(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    out = _run(sink, node, {'detections': [_person()]})

    assert out['track_count'] == 1
    assert out['tracks'][0]['track_id'] == 1
    assert out['tracks'][0]['class_name'] == 'person'
    # detections gains the id too, so downstream core nodes see it.
    assert out['detections'][0]['track_id'] == 1


def test_track_id_is_stable_across_frames(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    for step in range(4):
        out = _run(sink, node, {'detections': [_person(bbox=(200 + step * 4, 20, 260 + step * 4, 140))]})

    assert out['tracks'][0]['track_id'] == 1


def test_publishes_live_sv_object(node_classes):
    sv = pytest.importorskip('supervision')
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    out = _run(sink, node, {'detections': [_person()]})

    assert isinstance(out[SV_KEY], sv.Detections)
    assert out[SV_KEY].tracker_id.tolist() == [1]


def test_class_names_stay_attached_when_bytetrack_drops_a_detection(node_classes):
    """Regression: the tracker used to label surviving tracks by input index.

    The low-confidence car is first in the input list and is dropped by
    ByteTrack; the person survives. Indexing a parallel name list by output
    position returned 'car' for the person's box.
    """
    sink = node_classes['sink'](name='sink')
    node = _make(sink, track_thresh='0.5')

    out = _run(sink, node, {'detections': [_car(conf=0.30), _person(conf=0.95)]})

    assert out['track_count'] == 1
    assert out['tracks'][0]['class_name'] == 'person'
    assert out['tracks'][0]['class_id'] == 0


# --- reset ---------------------------------------------------------------

def test_reset_restarts_ids(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    _run(sink, node, {'detections': [_person(bbox=(200, 20, 260, 140))]})

    # A distant box gets no IoU match, so it starts a new track. ByteTrack needs
    # a second sighting to confirm it before it reports an id.
    _run(sink, node, {'detections': [_person(bbox=(10, 300, 70, 420))]})
    out = _run(sink, node, {'detections': [_person(bbox=(12, 300, 72, 420))]})
    assert out['tracks'][0]['track_id'] == 2

    node.reset()

    out = _run(sink, node, {'detections': [_person()]})
    assert out['tracks'][0]['track_id'] == 1
    assert node.tracker.frame_id == 1


def test_reset_is_a_declared_action():
    assert 'reset' in SupervisionTrackerNode.actions
    reset_prop = next(p for p in SupervisionTrackerNode.properties if p['name'] == 'reset')
    assert reset_prop['type'] == 'button' and reset_prop['action'] == 'reset'


# --- live tuning ---------------------------------------------------------

def test_config_change_keeps_existing_track_ids(node_classes):
    """Regression: re-configuring used to rebuild the tracker and wipe IDs."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    _run(sink, node, {'detections': [_person()]})
    tracker_before = node.tracker

    node.configure({'match_thresh': '0.6', 'track_thresh': '0.4'})

    out = _run(sink, node, {'detections': [_person(bbox=(204, 20, 264, 140))]})

    assert node.tracker is tracker_before        # same instance, not rebuilt
    assert out['tracks'][0]['track_id'] == 1     # id survived the edit
    assert node.tracker.minimum_matching_threshold == pytest.approx(0.6)
    assert node.tracker.track_activation_threshold == pytest.approx(0.4)
    assert node.tracker.det_thresh == pytest.approx(0.5)  # threshold + 0.1


def test_frame_rate_scales_the_lost_track_buffer(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, track_buffer='30', frame_rate='10')
    _run(sink, node, {'detections': [_person()]})

    # ByteTrack scales the buffer by frame_rate/30.
    assert node.tracker.max_time_lost == 10

    node.configure({'frame_rate': '60'})
    assert node.tracker.max_time_lost == 60


def test_min_consecutive_frames_suppresses_one_frame_tracks(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_consecutive_frames='3')

    assert node.tracker is None  # built lazily on first input
    out = _run(sink, node, {'detections': [_person()]})
    assert node.tracker.minimum_consecutive_frames == 3
    # A single sighting is not yet a confirmed track.
    assert out['track_count'] == 0


# --- no drawing ----------------------------------------------------------

def test_tracker_leaves_the_frame_untouched(node_classes):
    """Drawing belongs to SupervisionAnnotateNode; the tracker only tracks."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    image = np.zeros((240, 320, 3), dtype=np.uint8)
    out = _run(sink, node, {'image': image, 'detections': [_person(bbox=(40, 40, 120, 200))]})

    assert not out['image'].any()
    assert out['track_count'] == 1
    assert 'draw_tracks' not in [p['name'] for p in SupervisionTrackerNode.properties]


# --- pass-through / robustness ------------------------------------------

def test_no_detections_produces_empty_tracks(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    out = _run(sink, node, {'detections': []})

    assert out['tracks'] == [] and out['track_count'] == 0


def test_non_dict_payload_passes_through(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    node.on_input({'payload': 'just a string'})

    assert sink.received[-1]['payload'] == 'just a string'


def test_node_registers_in_supervision_category():
    assert SupervisionTrackerNode.category == 'supervision'


def test_degrades_gracefully_without_supervision(node_classes, monkeypatch):
    """A core install has no supervision: pass the message through, don't raise."""
    import pynode.nodes.Supervision.supervision_tracker_node as mod

    monkeypatch.setattr(mod, 'import_supervision', lambda: None)

    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    errors = []
    monkeypatch.setattr(node, 'report_error', lambda m: errors.append(m))

    node.on_input({'payload': {'detections': [_person()]}})
    node.on_input({'payload': {'detections': [_person()]}})

    # The flow keeps running, just without track ids.
    assert len(sink.received) == 2
    assert sink.received[-1]['payload']['detections'] == [_person()]
    assert 'tracks' not in sink.received[-1]['payload']
    # Reported once, not once per frame.
    assert len(errors) == 1
    assert 'supervision' in errors[0].lower()
