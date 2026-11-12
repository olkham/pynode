"""Tests for SupervisionReIDNode and its identity gallery.

No real Re-ID model is loaded (that would download weights): the node's encoder
is replaced by a fake that embeds a crop as its mean colour, so "appearance" is
simply the colour a test paints into a box. Nodes are driven directly through
``on_input`` and wired to the synchronous conftest sink - no Flask app, no
workflows dir, no worker threads.
"""

import threading

import numpy as np
import pytest

pytest.importorskip('supervision')

from pynode.nodes.Supervision import reid_gallery  # noqa: E402
from pynode.nodes.Supervision.reid_gallery import (  # noqa: E402
    IdentityGallery,
    get_shared_gallery,
    l2_normalize,
)
from pynode.nodes.Supervision.supervision_reid_node import (  # noqa: E402
    SupervisionReIDNode,
)
from pynode.nodes.supervision_utils import SV_KEY, labels_for  # noqa: E402

RED = (0, 0, 255)
GREEN = (0, 255, 0)
BLUE = (255, 0, 0)

BOX_A = (20, 20, 80, 160)
BOX_B = (150, 20, 210, 160)
BOX_C = (240, 20, 300, 160)


class FakeEncoder:
    """Embeds each box as the mean BGR colour of its crop."""

    def __init__(self):
        self.calls = 0
        self.boxes_embedded = 0

    def extract_embeddings(self, detections, frame):
        self.calls += 1
        self.boxes_embedded += len(detections)
        rows = []
        for x1, y1, x2, y2 in detections.xyxy.astype(int):
            rows.append(frame[y1:y2, x1:x2].reshape(-1, 3).mean(axis=0))
        return np.array(rows, dtype=np.float32).reshape(len(detections), 3)


@pytest.fixture(autouse=True)
def _isolated_galleries():
    reid_gallery.clear_shared_galleries()
    yield
    reid_gallery.clear_shared_galleries()


def _make(node_classes, name='cam', **config):
    node = SupervisionReIDNode(name=name)
    node.configure({'refresh_interval': '1', **config})
    encoder = FakeEncoder()
    node._model = encoder
    node._model_lock = threading.Lock()
    node._model_key = (node._model_source(), 'auto')
    sink = node_classes['sink'](name='sink')
    events = node_classes['sink'](name='events')
    node.connect(sink, output_index=0)
    node.connect(events, output_index=1)
    return node, sink, events, encoder


def _frame(*painted):
    image = np.zeros((200, 320, 3), dtype=np.uint8)
    for (x1, y1, x2, y2), colour in painted:
        image[y1:y2, x1:x2] = colour
    return image


def _det(bbox, track_id=None, class_name='person', class_id=0):
    det = {'bbox': list(bbox), 'class_id': class_id, 'class_name': class_name, 'confidence': 0.9}
    if track_id is not None:
        det['track_id'] = track_id
    return det


def _run(node, sink, painted, detections):
    node.on_input({'payload': {'image': _frame(*painted), 'detections': detections}})
    return sink.received[-1]['payload']


def _event_kinds(events):
    return [m['payload']['event'] for m in events.received]


# --- gallery -------------------------------------------------------------

def test_gallery_matches_within_threshold_and_rejects_beyond():
    gallery = IdentityGallery()
    red = gallery.add(l2_normalize(np.array([1.0, 0.0, 0.0]))[0])

    near = l2_normalize(np.array([[0.95, 0.1, 0.0]]))
    far = l2_normalize(np.array([[0.0, 1.0, 0.0]]))

    assert gallery.match(near, 0.3)[0][0] == red
    identity, distance = gallery.match(far, 0.3)[0]
    assert identity is None and distance == pytest.approx(1.0)


def test_gallery_assignment_is_one_to_one():
    gallery = IdentityGallery()
    only = gallery.add(l2_normalize(np.array([1.0, 0.0, 0.0]))[0])

    two_lookalikes = l2_normalize(np.array([[1.0, 0.0, 0.0], [0.98, 0.05, 0.0]]))
    matched = [identity for identity, _ in gallery.match(two_lookalikes, 0.3)]

    assert matched.count(only) == 1 and matched.count(None) == 1
    assert matched[0] == only   # the closer one wins


def test_gallery_exclude_and_empty():
    gallery = IdentityGallery()
    query = l2_normalize(np.array([[1.0, 0.0, 0.0]]))
    assert gallery.match(query, 0.3) == [(None, None)]

    identity = gallery.add(query[0])
    assert gallery.match(query, 0.3, exclude={identity})[0][0] is None


def test_gallery_prune_by_ttl_and_size():
    gallery = IdentityGallery()
    vec = l2_normalize(np.array([1.0, 0.0, 0.0]))[0]
    old = gallery.add(vec, now=0.0)
    mid = gallery.add(vec, now=50.0)
    new = gallery.add(vec, now=100.0)

    assert gallery.prune(ttl_seconds=60, now=100.0) == [old]
    assert gallery.ids() == [mid, new]

    assert gallery.prune(max_identities=1, now=100.0) == [mid]
    assert gallery.ids() == [new]

    # `keep` protects identities in use this frame.
    assert gallery.prune(ttl_seconds=1, now=500.0, keep={new}) == []


def test_gallery_update_is_an_ema_and_stays_unit_length():
    gallery = IdentityGallery()
    identity = gallery.add(np.array([1.0, 0.0], dtype=np.float32))
    gallery.update(identity, np.array([0.0, 1.0], dtype=np.float32), alpha=0.5)

    feature = gallery._features[identity]
    assert np.linalg.norm(feature) == pytest.approx(1.0, abs=1e-5)
    assert feature[0] == pytest.approx(feature[1])


def test_shared_gallery_is_keyed_by_name_and_model():
    assert get_shared_gallery('lobby', 'm1') is get_shared_gallery('lobby', 'm1')
    assert get_shared_gallery('lobby', 'm1') is not get_shared_gallery('lobby', 'm2')
    assert get_shared_gallery('lobby', 'm1') is not get_shared_gallery('dock', 'm1')


# --- identification ------------------------------------------------------

def test_assigns_distinct_identities_by_appearance(node_classes):
    node, sink, events, _ = _make(node_classes)

    out = _run(node, sink, [(BOX_A, RED), (BOX_B, GREEN)], [_det(BOX_A), _det(BOX_B)])

    assert [d['reid_id'] for d in out['detections']] == [1, 2]
    assert out['identity_count'] == 2
    assert [i['reid_id'] for i in out['identities']] == [1, 2]
    assert _event_kinds(events) == ['new', 'new']
    assert out[SV_KEY].data['reid_id'].tolist() == [1, 2]


def test_identity_follows_appearance_not_position(node_classes):
    node, sink, _, _ = _make(node_classes)

    _run(node, sink, [(BOX_A, RED), (BOX_B, GREEN)], [_det(BOX_A), _det(BOX_B)])
    # The two swap places.
    out = _run(node, sink, [(BOX_A, GREEN), (BOX_B, RED)], [_det(BOX_A), _det(BOX_B)])

    assert [d['reid_id'] for d in out['detections']] == [2, 1]
    assert out['identity_count'] == 2


def test_identity_survives_a_new_track_id(node_classes):
    """The point of Re-ID: the tracker lost the person and restarted their id."""
    node, sink, events, _ = _make(node_classes)

    _run(node, sink, [(BOX_A, RED)], [_det(BOX_A, track_id=4)])
    _run(node, sink, [], [])
    out = _run(node, sink, [(BOX_C, RED)], [_det(BOX_C, track_id=9)])

    assert out['detections'][0]['reid_id'] == 1
    assert out['detections'][0]['track_id'] == 9
    assert _event_kinds(events) == ['new', 'reidentified']
    event = events.received[-1]['payload']
    assert event['reid_id'] == 1 and event['track_id'] == 9
    assert events.received[-1]['topic'] == 'reid/reidentified'


def test_a_tracked_object_keeps_its_identity_even_if_it_changes_colour(node_classes):
    """An established track link beats appearance (lighting changes, turning)."""
    node, sink, events, _ = _make(node_classes)

    _run(node, sink, [(BOX_A, RED)], [_det(BOX_A, track_id=1)])
    out = _run(node, sink, [(BOX_A, BLUE)], [_det(BOX_A, track_id=1)])

    assert out['detections'][0]['reid_id'] == 1
    assert out['identity_count'] == 1
    assert _event_kinds(events) == ['new']


def test_two_boxes_cannot_share_an_identity_in_one_frame(node_classes):
    node, sink, _, _ = _make(node_classes)

    _run(node, sink, [(BOX_A, RED)], [_det(BOX_A)])
    out = _run(node, sink, [(BOX_A, RED), (BOX_B, RED)], [_det(BOX_A), _det(BOX_B)])

    ids = [d['reid_id'] for d in out['detections']]
    assert sorted(ids) == [1, 2]


def test_refresh_interval_skips_embedding_for_tracked_objects(node_classes):
    node, sink, _, encoder = _make(node_classes, refresh_interval='5')

    for _ in range(5):
        out = _run(node, sink, [(BOX_A, RED)], [_det(BOX_A, track_id=1)])

    assert out['detections'][0]['reid_id'] == 1
    assert encoder.boxes_embedded == 1   # only the first sighting

    _run(node, sink, [(BOX_A, RED)], [_det(BOX_A, track_id=1)])
    assert encoder.boxes_embedded == 2   # refreshed on the 6th frame


def test_untracked_detections_do_not_spam_reidentified_events(node_classes):
    node, sink, events, _ = _make(node_classes)

    for _ in range(4):
        out = _run(node, sink, [(BOX_A, RED)], [_det(BOX_A)])

    assert out['detections'][0]['reid_id'] == 1
    assert _event_kinds(events) == ['new']


# --- options -------------------------------------------------------------

def test_class_filter_only_identifies_wanted_classes(node_classes):
    node, sink, _, _ = _make(node_classes, classes='person')

    out = _run(node, sink, [(BOX_A, RED), (BOX_B, GREEN)],
               [_det(BOX_A), _det(BOX_B, class_name='car', class_id=2)])

    assert out['detections'][0]['reid_id'] == 1
    assert 'reid_id' not in out['detections'][1]
    assert out['identity_count'] == 1

    node.configure({'classes': ''})
    out = _run(node, sink, [(BOX_A, RED), (BOX_B, GREEN)],
               [_det(BOX_A), _det(BOX_B, class_name='car', class_id=2)])
    assert 'reid_id' in out['detections'][1]


def test_small_boxes_are_skipped(node_classes):
    node, sink, _, encoder = _make(node_classes, min_box_size='32')
    tiny = (10, 10, 20, 20)

    out = _run(node, sink, [(tiny, RED)], [_det(tiny)])

    assert 'reid_id' not in out['detections'][0]
    assert encoder.calls == 0


def test_use_as_track_id_replaces_track_ids(node_classes):
    node, sink, _, _ = _make(node_classes, use_as_track_id=True)

    _run(node, sink, [(BOX_A, RED)], [_det(BOX_A, track_id=40)])
    out = _run(node, sink, [(BOX_B, RED)], [_det(BOX_B, track_id=77)])

    assert out['detections'][0]['track_id'] == 1
    assert out[SV_KEY].tracker_id.tolist() == [1]
    assert out[SV_KEY].data['local_track_id'].tolist() == [77]


def test_does_not_mutate_the_upstream_detections_object(node_classes):
    sv = pytest.importorskip('supervision')
    node, sink, _, _ = _make(node_classes, use_as_track_id=True)
    upstream = sv.Detections(
        xyxy=np.array([BOX_A], dtype=np.float32), confidence=np.array([0.9], dtype=np.float32),
        class_id=np.array([0]), tracker_id=np.array([55]),
        data={'class_name': np.array(['person'])})

    node.on_input({'payload': {'image': _frame((BOX_A, RED)), SV_KEY: upstream}})

    assert upstream.tracker_id.tolist() == [55]
    assert 'reid_id' not in upstream.data
    assert sink.received[-1]['payload'][SV_KEY].tracker_id.tolist() == [1]


def test_include_embeddings_attaches_json_safe_vectors(node_classes):
    import json

    node, sink, _, _ = _make(node_classes, include_embeddings=True)

    out = _run(node, sink, [(BOX_A, RED)], [_det(BOX_A)])

    embedding = out['detections'][0]['embedding']
    assert len(embedding) == 3 and all(isinstance(v, float) for v in embedding)
    json.dumps(out['detections'])


def test_reset_forgets_identities(node_classes):
    node, sink, _, _ = _make(node_classes)
    _run(node, sink, [(BOX_A, RED)], [_det(BOX_A, track_id=1)])

    assert node.reset() == {'status': 'reset'}
    out = _run(node, sink, [(BOX_A, GREEN)], [_det(BOX_A, track_id=1)])

    assert out['detections'][0]['reid_id'] == 1 and out['identity_count'] == 1
    assert 'reset' in SupervisionReIDNode.actions


def test_max_identities_caps_the_gallery(node_classes):
    node, sink, _, _ = _make(node_classes, max_identities='2')

    for colour in (RED, GREEN, BLUE):
        out = _run(node, sink, [(BOX_A, colour)], [_det(BOX_A)])

    assert out['identity_count'] <= 2


# --- cross-camera --------------------------------------------------------

def test_shared_gallery_gives_one_identity_across_two_nodes(node_classes):
    cam1, sink1, _, _ = _make(node_classes, name='cam1', gallery='site')
    cam2, sink2, events2, _ = _make(node_classes, name='cam2', gallery='site')

    out1 = _run(cam1, sink1, [(BOX_A, RED)], [_det(BOX_A, track_id=3)])
    out2 = _run(cam2, sink2, [(BOX_C, RED)], [_det(BOX_C, track_id=3)])

    assert out1['detections'][0]['reid_id'] == out2['detections'][0]['reid_id'] == 1
    event = events2.received[-1]['payload']
    assert event['event'] == 'reidentified'
    assert event['previous_source'] == 'cam1' and event['source'] == 'cam2'
    assert event['gallery'] == 'site'


def test_private_galleries_are_independent(node_classes):
    cam1, sink1, _, _ = _make(node_classes, name='cam1')
    cam2, sink2, events2, _ = _make(node_classes, name='cam2')

    _run(cam1, sink1, [(BOX_A, RED)], [_det(BOX_A)])
    _run(cam1, sink1, [(BOX_A, GREEN)], [_det(BOX_A)])
    out2 = _run(cam2, sink2, [(BOX_A, GREEN)], [_det(BOX_A)])

    assert out2['detections'][0]['reid_id'] == 1   # cam2's own numbering
    assert _event_kinds(events2) == ['new']


# --- robustness ----------------------------------------------------------

def test_no_image_reports_once_and_passes_through(node_classes, monkeypatch):
    node, sink, _, _ = _make(node_classes)
    errors = []
    monkeypatch.setattr(node, 'report_error', lambda m: errors.append(m))

    node.on_input({'payload': {'detections': [_det(BOX_A)]}})
    node.on_input({'payload': {'detections': [_det(BOX_A)]}})

    assert len(sink.received) == 2
    assert 'reid_id' not in sink.received[-1]['payload']['detections'][0]
    assert len(errors) == 1 and 'payload.image' in errors[0]


def test_empty_frame_and_non_dict_payload(node_classes):
    node, sink, events, _ = _make(node_classes)

    out = _run(node, sink, [], [])
    assert out['identities'] == [] and out['identity_count'] == 0

    node.on_input({'payload': 'text'})
    assert sink.received[-1]['payload'] == 'text'
    assert events.received == []


def test_encoder_failure_is_reported_and_message_still_flows(node_classes, monkeypatch):
    node, sink, _, encoder = _make(node_classes)
    errors = []
    monkeypatch.setattr(node, 'report_error', lambda m: errors.append(m))
    monkeypatch.setattr(encoder, 'extract_embeddings',
                        lambda d, f: (_ for _ in ()).throw(RuntimeError('cuda oom')))

    node.on_input({'payload': {'image': _frame((BOX_A, RED)), 'detections': [_det(BOX_A)]}})

    assert len(sink.received) == 1
    assert errors and 'cuda oom' in errors[0]


def test_model_loads_in_background_and_frames_pass_through_meanwhile(node_classes, monkeypatch):
    node = SupervisionReIDNode(name='cam')
    sink = node_classes['sink'](name='sink')
    node.connect(sink)
    release = threading.Event()
    encoder = FakeEncoder()

    def _slow_load(source, device):
        release.wait(5)
        return encoder

    # A unique source keeps this test off the process-wide model cache.
    node.configure({'model': 'custom', 'custom_model': 'test://slow-load'})
    monkeypatch.setattr(node, '_load_model', _slow_load)

    try:
        node.on_input({'payload': {'image': _frame((BOX_A, RED)), 'detections': [_det(BOX_A)]}})
        assert 'reid_id' not in sink.received[-1]['payload']['detections'][0]
        assert node._loading is True
    finally:
        release.set()
        for thread in threading.enumerate():
            if thread.name == f"reid-load-{node.id}":
                thread.join(5)

    out = _run(node, sink, [(BOX_A, RED)], [_det(BOX_A)])
    assert out['detections'][0]['reid_id'] == 1


def test_missing_reid_package_is_reported_once(node_classes, monkeypatch):
    node = SupervisionReIDNode(name='cam')
    sink = node_classes['sink'](name='sink')
    node.connect(sink)
    node.configure({'model': 'custom', 'custom_model': 'test://missing-package'})
    errors = []
    monkeypatch.setattr(node, 'report_error', lambda m: errors.append(m))

    def _no_reid(source, device):
        raise ImportError("No module named 'reid'")

    monkeypatch.setattr(node, '_load_model', _no_reid)

    for _ in range(3):
        node.on_input({'payload': {'image': _frame((BOX_A, RED)), 'detections': [_det(BOX_A)]}})
        for thread in threading.enumerate():
            if thread.name == f"reid-load-{node.id}":
                thread.join(5)

    assert len(sink.received) == 3
    assert len(errors) == 1 and 'pynode-flow[reid]' in errors[0]


# --- labels --------------------------------------------------------------

def test_labels_show_the_identity_instead_of_the_local_track_id(node_classes):
    node, sink, _, _ = _make(node_classes)
    out = _run(node, sink, [(BOX_A, RED)], [_det(BOX_A, track_id=12)])

    assert labels_for(out[SV_KEY], show_confidence=False) == ['ID1 person']


def test_node_metadata():
    assert SupervisionReIDNode.category == 'supervision'
    assert SupervisionReIDNode.output_count == 2
    names = [p['name'] for p in SupervisionReIDNode.properties]
    assert {'model', 'gallery', 'match_distance', 'use_as_track_id', 'reset'} <= set(names)
