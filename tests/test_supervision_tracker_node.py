"""Tests for SupervisionTrackerNode.

The node is driven directly via ``on_input`` and wired to the conftest 'sink'
(synchronous ``on_input_direct`` delivery) - no Flask app, no workflows dir, no
worker threads started, so nothing here can touch real workflow data.

The tracker does not draw - visualisation lives in SupervisionAnnotateNode.
Tracking algorithms come from Roboflow's ``trackers`` package (supervision 0.31
removed ``sv.ByteTrack``).
"""

import numpy as np
import pytest

pytest.importorskip('supervision')
pytest.importorskip('trackers')

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


def _confirm(sink, node, bbox=(200, 20, 260, 140)):
    """Feed the same box twice: a track is reported from its second sighting."""
    _run(sink, node, {'detections': [_person(bbox=bbox)]})
    return _run(sink, node, {'detections': [_person(bbox=bbox)]})


# --- core behaviour ------------------------------------------------------

def test_assigns_track_ids(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    first = _run(sink, node, {'detections': [_person()]})
    # A brand-new object is unconfirmed on its first sighting.
    assert first['track_count'] == 0 and first['detections'] == []

    out = _run(sink, node, {'detections': [_person()]})

    assert out['track_count'] == 1
    assert out['tracks'][0]['track_id'] == 0
    assert out['tracks'][0]['class_name'] == 'person'
    # detections gains the id too, so downstream core nodes see it.
    assert out['detections'][0]['track_id'] == 0


def test_track_id_is_stable_across_frames(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    for step in range(4):
        out = _run(sink, node, {'detections': [_person(bbox=(200 + step * 4, 20, 260 + step * 4, 140))]})

    assert out['tracks'][0]['track_id'] == 0


def test_publishes_live_sv_object(node_classes):
    sv = pytest.importorskip('supervision')
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    out = _confirm(sink, node)

    assert isinstance(out[SV_KEY], sv.Detections)
    assert out[SV_KEY].tracker_id.tolist() == [0]


def test_class_names_stay_attached_when_a_detection_is_dropped(node_classes):
    """Regression: the tracker used to label surviving tracks by input index.

    The low-confidence car is first in the input list and never gets a track;
    the person survives. Indexing a parallel name list by output position
    returned 'car' for the person's box.
    """
    sink = node_classes['sink'](name='sink')
    node = _make(sink, track_thresh='0.5')

    _run(sink, node, {'detections': [_car(conf=0.30), _person(conf=0.95)]})
    out = _run(sink, node, {'detections': [_car(conf=0.30), _person(conf=0.95)]})

    assert out['track_count'] == 1
    assert out['tracks'][0]['class_name'] == 'person'
    assert out['tracks'][0]['class_id'] == 0


# --- reset ---------------------------------------------------------------

def test_reset_restarts_ids(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    _confirm(sink, node, bbox=(200, 20, 260, 140))

    # A distant box gets no IoU match, so it starts a new track.
    out = _confirm(sink, node, bbox=(10, 300, 70, 420))
    assert out['tracks'][0]['track_id'] == 1

    node.reset()

    out = _confirm(sink, node)
    assert out['tracks'][0]['track_id'] == 0


def test_reset_is_a_declared_action():
    assert 'reset' in SupervisionTrackerNode.actions
    reset_prop = next(p for p in SupervisionTrackerNode.properties if p['name'] == 'reset')
    assert reset_prop['type'] == 'button' and reset_prop['action'] == 'reset'


# --- live tuning ---------------------------------------------------------

def test_config_change_keeps_existing_track_ids(node_classes):
    """Regression: re-configuring used to rebuild the tracker and wipe IDs."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    _confirm(sink, node)
    tracker_before = node.tracker

    node.configure({'min_iou': '0.4', 'track_thresh': '0.4', 'high_thresh': '0.5',
                    'min_consecutive_frames': '2'})

    out = _run(sink, node, {'detections': [_person(bbox=(204, 20, 264, 140))]})

    assert node.tracker is tracker_before        # same instance, not rebuilt
    assert out['tracks'][0]['track_id'] == 0     # id survived the edit
    assert node.tracker.minimum_iou_threshold == pytest.approx(0.4)
    assert node.tracker.track_activation_threshold == pytest.approx(0.4)
    assert node.tracker.high_conf_det_threshold == pytest.approx(0.5)
    assert node.tracker.minimum_consecutive_frames == 2


def test_blank_high_threshold_follows_tracking_threshold(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, track_thresh='0.35', high_thresh='')
    _run(sink, node, {'detections': [_person()]})

    assert node.tracker.high_conf_det_threshold == pytest.approx(0.35)


def test_frame_rate_scales_the_lost_track_buffer(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, track_buffer='30', frame_rate='10')
    _run(sink, node, {'detections': [_person()]})

    # The buffer is expressed in 30 FPS frames and scaled to the source rate.
    assert node.tracker.maximum_frames_without_update == 10

    # Frame rate is structural: the tracker is rebuilt on the next frame.
    node.configure({'frame_rate': '60'})
    _run(sink, node, {'detections': [_person()]})
    assert node.tracker.maximum_frames_without_update == 60


def test_legacy_match_thresh_is_translated_to_min_iou(node_classes):
    """sv.ByteTrack's match_thresh was an IoU distance: 0.8 meant IoU >= 0.2."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink, match_thresh='0.7')

    assert 'match_thresh' not in node.config
    assert float(node.config['min_iou']) == pytest.approx(0.3)

    # An explicit min_iou wins over a stale legacy key.
    node = _make(sink, match_thresh='0.7', min_iou='0.15')
    assert float(node.config['min_iou']) == pytest.approx(0.15)


def test_malformed_numbers_fall_back_to_defaults(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, track_thresh='', track_buffer='abc', min_iou=None, frame_rate='')

    out = _confirm(sink, node)

    assert out['track_count'] == 1
    assert node.tracker.track_activation_threshold == pytest.approx(0.25)


def test_min_consecutive_frames_suppresses_one_frame_tracks(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min_consecutive_frames='3')

    assert node.tracker is None  # built lazily on first input
    out = _run(sink, node, {'detections': [_person()]})
    assert node.tracker.minimum_consecutive_frames == 3
    # A single sighting is not yet a confirmed track.
    assert out['track_count'] == 0

    for _ in range(6):
        out = _run(sink, node, {'detections': [_person()]})
    assert out['track_count'] == 1


# --- algorithms ----------------------------------------------------------

@pytest.mark.parametrize('algorithm, class_name', [
    ('bytetrack', 'ByteTrackTracker'),
    ('sort', 'SORTTracker'),
    ('ocsort', 'OCSORTTracker'),
    ('botsort', 'BoTSORTTracker'),
    ('nonsense', 'ByteTrackTracker'),
])
def test_algorithm_selection(node_classes, algorithm, class_name):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, algorithm=algorithm)

    for step in range(5):
        out = _run(sink, node, {'detections': [_person(bbox=(200 + step * 2, 20, 260 + step * 2, 140))]})

    assert type(node.tracker).__name__ == class_name
    assert out['track_count'] == 1
    assert out['tracks'][0]['class_name'] == 'person'


def test_changing_algorithm_rebuilds_the_tracker(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink)
    _confirm(sink, node)
    before = node.tracker

    node.configure({'algorithm': 'sort'})
    _run(sink, node, {'detections': [_person()]})

    assert node.tracker is not before
    assert type(node.tracker).__name__ == 'SORTTracker'


def test_keep_untracked_passes_unconfirmed_detections_without_an_id(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, keep_untracked=True)

    out = _run(sink, node, {'detections': [_person()]})

    assert len(out['detections']) == 1
    assert 'track_id' not in out['detections'][0]   # -1 is not an identity
    assert out['tracks'] == [] and out['track_count'] == 0


def test_camera_motion_uses_the_frame(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, algorithm='botsort', camera_motion=True)
    rng = np.random.default_rng(0)
    image = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)

    for _ in range(3):
        out = _run(sink, node, {'image': image, 'detections': [_person(bbox=(40, 40, 120, 200))]})

    assert node._needs_frame is True
    assert out['track_count'] == 1


def test_camera_motion_without_an_image_reports_once_and_keeps_tracking(node_classes, monkeypatch):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, algorithm='botsort', camera_motion=True)
    errors = []
    monkeypatch.setattr(node, 'report_error', lambda m: errors.append(m))

    for _ in range(3):
        out = _run(sink, node, {'detections': [_person()]})

    assert out['track_count'] == 1
    assert len(errors) == 1 and 'payload.image' in errors[0]


def test_build_failure_is_reported_once_and_passes_through(node_classes, monkeypatch):
    sink = node_classes['sink'](name='sink')
    node = _make(sink)
    errors = []
    monkeypatch.setattr(node, 'report_error', lambda m: errors.append(m))

    def _boom(_module):
        raise RuntimeError('no weights')

    monkeypatch.setattr(node, '_build_tracker', _boom)

    node.on_input({'payload': {'detections': [_person()]}})
    node.on_input({'payload': {'detections': [_person()]}})

    assert len(sink.received) == 2
    assert len(errors) == 1 and 'no weights' in errors[0]


# --- no drawing ----------------------------------------------------------

def test_tracker_leaves_the_frame_untouched(node_classes):
    """Drawing belongs to SupervisionAnnotateNode; the tracker only tracks."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink)

    image = np.zeros((240, 320, 3), dtype=np.uint8)
    _run(sink, node, {'image': image, 'detections': [_person(bbox=(40, 40, 120, 200))]})
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


def test_degrades_gracefully_without_trackers(node_classes, monkeypatch):
    """supervision present but the trackers package missing (pre-0.31 install)."""
    import pynode.nodes.Supervision.supervision_tracker_node as mod

    monkeypatch.setattr(mod, 'import_trackers', lambda: None)

    sink = node_classes['sink'](name='sink')
    node = _make(sink)
    errors = []
    monkeypatch.setattr(node, 'report_error', lambda m: errors.append(m))

    node.on_input({'payload': {'detections': [_person()]}})
    node.on_input({'payload': {'detections': [_person()]}})

    assert len(sink.received) == 2
    assert 'tracks' not in sink.received[-1]['payload']
    assert len(errors) == 1 and 'trackers' in errors[0].lower()
