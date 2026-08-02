"""Tests for the shared supervision conversion helpers.

These are pure function tests - no Flask app, no workflows dir, no threads.
Skipped wholesale when supervision is not installed (it lives in the [vision]
extra, so a core install legitimately lacks it).
"""

import numpy as np
import pytest

sv = pytest.importorskip('supervision')

from pynode.nodes.supervision_utils import (  # noqa: E402
    SV_KEY,
    import_supervision,
    labels_for,
    sv_to_list,
    to_sv,
    write_back,
)


def _dets():
    return [
        {'bbox': [10, 10, 50, 90], 'class_id': 2, 'class_name': 'car', 'confidence': 0.30},
        {'bbox': [200, 20, 260, 140], 'class_id': 0, 'class_name': 'person', 'confidence': 0.95},
    ]


# --- to_sv ---------------------------------------------------------------

def test_to_sv_builds_detections_from_list():
    d = to_sv({'detections': _dets()})

    assert len(d) == 2
    assert d.xyxy.tolist() == [[10, 10, 50, 90], [200, 20, 260, 140]]
    assert d.class_id.tolist() == [2, 0]
    assert d.data['class_name'].tolist() == ['car', 'person']
    # No track ids in the source -> none on the Detections.
    assert d.tracker_id is None


def test_to_sv_prefers_live_object():
    """A live payload.sv is returned as-is, not rebuilt from the dict list."""
    live = sv.Detections(
        xyxy=np.array([[1., 2., 3., 4.]]),
        class_id=np.array([7]),
    )
    # The list disagrees with the live object on purpose.
    d = to_sv({SV_KEY: live, 'detections': _dets()})

    assert d is live
    assert d.class_id.tolist() == [7]


def test_to_sv_carries_track_ids():
    dets = _dets()
    dets[0]['track_id'] = 4
    dets[1]['track_id'] = 9

    d = to_sv({'detections': dets})
    assert d.tracker_id.tolist() == [4, 9]


@pytest.mark.parametrize('payload', [
    {},
    {'detections': []},
    {'detections': None},
    'not-a-dict',
    {'detections': [{'class_name': 'car'}]},           # no bbox
    {'detections': [{'bbox': [1, 2, 3]}]},             # wrong length
])
def test_to_sv_empty_and_malformed(payload):
    d = to_sv(payload)
    assert len(d) == 0


def test_to_sv_skips_only_the_bad_entries():
    d = to_sv({'detections': [
        {'bbox': [0, 0, 10, 10], 'class_name': 'a', 'class_id': 1, 'confidence': 0.5},
        {'bbox': [1, 2, 3]},  # malformed, dropped
        {'bbox': [20, 20, 30, 30], 'class_name': 'b', 'class_id': 2, 'confidence': 0.6},
    ]})

    assert len(d) == 2
    assert d.data['class_name'].tolist() == ['a', 'b']


# --- alignment regression ------------------------------------------------

def test_class_names_survive_filtering_and_reordering():
    """The bug this module exists to prevent.

    Carrying class names in a parallel Python list and indexing it by output
    position mislabels objects as soon as anything filters or reorders the
    Detections. Riding in ``data`` keeps each name attached to its own box.
    """
    d = to_sv({'detections': [
        {'bbox': [0, 0, 10, 10], 'class_id': 0, 'class_name': 'person', 'confidence': 0.9},
        {'bbox': [20, 20, 30, 30], 'class_id': 2, 'class_name': 'car', 'confidence': 0.5},
        {'bbox': [40, 40, 50, 50], 'class_id': 16, 'class_name': 'dog', 'confidence': 0.7},
    ]})

    # Keep dog and person, in that order - both filtered AND reordered.
    reordered = d[np.array([2, 0])]

    assert [e['class_name'] for e in sv_to_list(reordered)] == ['dog', 'person']
    assert [e['class_id'] for e in sv_to_list(reordered)] == [16, 0]


# --- sv_to_list / write_back --------------------------------------------

def test_sv_to_list_round_trips():
    original = _dets()
    out = sv_to_list(to_sv({'detections': original}))

    assert len(out) == 2
    assert [e['class_name'] for e in out] == ['car', 'person']
    assert [e['class_id'] for e in out] == [2, 0]
    assert out[0]['bbox'] == [10.0, 10.0, 50.0, 90.0]
    assert out[0]['bbox_wh'] == [10.0, 10.0, 40.0, 80.0]
    assert out[0]['confidence'] == pytest.approx(0.30, abs=1e-6)
    # No tracker ids on the source, so none reported.
    assert 'track_id' not in out[0]


def test_sv_to_list_empty():
    assert sv_to_list(sv.Detections.empty()) == []
    assert sv_to_list(None) == []


def test_write_back_sets_both_forms():
    payload = {'detections': _dets()}
    d = to_sv(payload)

    entries = write_back(d, payload)

    assert payload[SV_KEY] is d                    # live object for sv nodes
    assert payload['detections'] == entries        # interop list for core nodes
    assert payload['detection_count'] == 2


def test_write_back_custom_keys():
    payload = {}
    write_back(to_sv({'detections': _dets()}), payload,
               list_key='tracks', count_key='track_count')

    assert payload['track_count'] == 2
    assert len(payload['tracks']) == 2


# --- labels --------------------------------------------------------------

def test_labels_use_class_names():
    d = to_sv({'detections': _dets()})
    assert labels_for(d, show_confidence=False) == ['car', 'person']


def test_labels_include_track_id_and_confidence():
    dets = _dets()
    dets[0]['track_id'] = 3
    dets[1]['track_id'] = 8

    assert labels_for(to_sv({'detections': dets})) == ['#3 car 0.30', '#8 person 0.95']


def test_labels_fall_back_to_class_id():
    d = sv.Detections(xyxy=np.array([[0., 0., 1., 1.]]), class_id=np.array([5]))
    assert labels_for(d, show_confidence=False) == ['#5']


def test_labels_empty():
    assert labels_for(sv.Detections.empty()) == []
    assert labels_for(None) == []


# --- import helper -------------------------------------------------------

def test_import_supervision_is_cached():
    assert import_supervision() is import_supervision() is sv
