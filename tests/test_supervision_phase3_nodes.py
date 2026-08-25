"""Tests for SupervisionSmootherNode, SupervisionFilterNode, SupervisionSinkNode.

Driven directly via ``on_input`` wired to conftest sinks - no Flask app, no
workflows dir, no worker threads. Sink files are written ONLY into tmp_path.
"""

import csv
import json

import numpy as np
import pytest

sv = pytest.importorskip('supervision')

from pynode.nodes.Supervision.supervision_filter_node import (  # noqa: E402
    SupervisionFilterNode,
)
from pynode.nodes.Supervision.supervision_sink_node import (  # noqa: E402
    SupervisionSinkNode,
)
from pynode.nodes.Supervision.supervision_smoother_node import (  # noqa: E402
    SupervisionSmootherNode,
)


def _det(bbox, tid=None, cid=0, name='person', conf=0.9):
    d = {'bbox': list(bbox), 'class_id': cid, 'class_name': name, 'confidence': conf}
    if tid is not None:
        d['track_id'] = tid
    return d


# --- smoother ------------------------------------------------------------

def _smoother(sink, **config):
    node = SupervisionSmootherNode(name='sm')
    if config:
        node.configure(config)
    node.connect(sink)
    return node


def test_smoother_averages_jittery_boxes(node_classes):
    sink = node_classes['sink'](name='s')
    node = _smoother(sink, length='4')

    for x in (100, 108, 100, 108):
        node.on_input({'payload': {'detections': [
            _det((x, 100, x + 50, 200), tid=1)]}})

    out = sink.received[-1]['payload']
    x1 = out['detections'][0]['bbox'][0]
    assert x1 == pytest.approx(104.0)          # mean of the window
    assert out['detections'][0]['class_name'] == 'person'
    assert out['detections'][0]['track_id'] == 1


def test_smoother_updates_tracks_mirror(node_classes):
    sink = node_classes['sink'](name='s')
    node = _smoother(sink)

    node.on_input({'payload': {
        'detections': [_det((100, 100, 150, 200), tid=1)],
        'tracks': [_det((100, 100, 150, 200), tid=1)],
        'track_count': 1}})

    out = sink.received[-1]['payload']
    assert out['tracks'] == out['detections']


def test_smoother_without_track_ids_warns_once_and_passes(node_classes):
    sink = node_classes['sink'](name='s')
    node = _smoother(sink)
    errors = []
    node.report_error = lambda m: errors.append(m)

    node.on_input({'payload': {'detections': [_det((100, 100, 150, 200))]}})
    node.on_input({'payload': {'detections': [_det((100, 100, 150, 200))]}})

    assert len(sink.received) == 2
    assert sink.received[-1]['payload']['detections'][0]['bbox'] == [100, 100, 150, 200]
    assert len(errors) == 1 and 'Tracker' in errors[0]


def test_smoother_reset_and_length_change(node_classes):
    sink = node_classes['sink'](name='s')
    node = _smoother(sink, length='4')
    node.on_input({'payload': {'detections': [_det((100, 100, 150, 200), tid=1)]}})
    first = node.smoother

    node.configure({'length': '8'})
    assert node.smoother is not first          # window change rebuilds

    node.reset()
    assert node.smoother is not None


# --- filter --------------------------------------------------------------

def _filter(kept, rejected, **config):
    node = SupervisionFilterNode(name='f')
    if config:
        node.configure(config)
    node.connect(kept, output_index=0)
    node.connect(rejected, output_index=1)
    return node


def _run_filter(node, kept, rejected, dets):
    node.on_input({'payload': {'detections': dets}})
    return (kept.received[-1]['payload'], rejected.received[-1]['payload'])


def test_filter_confidence_range(node_classes):
    kept, rej = node_classes['sink'](name='k'), node_classes['sink'](name='r')
    node = _filter(kept, rej, min_confidence='0.5', max_confidence='0.95')

    k, r = _run_filter(node, kept, rej, [
        _det((0, 0, 10, 10), conf=0.3, name='low'),
        _det((20, 0, 30, 10), conf=0.7, name='mid'),
        _det((40, 0, 50, 10), conf=0.99, name='high'),
    ])
    assert [d['class_name'] for d in k['detections']] == ['mid']
    assert sorted(d['class_name'] for d in r['detections']) == ['high', 'low']


def test_filter_allow_deny_classes(node_classes):
    kept, rej = node_classes['sink'](name='k'), node_classes['sink'](name='r')
    node = _filter(kept, rej, allow_classes='person, 2', deny_classes='dog')

    k, r = _run_filter(node, kept, rej, [
        _det((0, 0, 10, 10), cid=0, name='person'),
        _det((20, 0, 30, 10), cid=2, name='car'),      # allowed via id '2'
        _det((40, 0, 50, 10), cid=16, name='dog'),
        _det((60, 0, 70, 10), cid=7, name='truck'),    # not in allow list
    ])
    assert [d['class_name'] for d in k['detections']] == ['person', 'car']
    assert sorted(d['class_name'] for d in r['detections']) == ['dog', 'truck']


def test_filter_area_and_aspect(node_classes):
    kept, rej = node_classes['sink'](name='k'), node_classes['sink'](name='r')
    node = _filter(kept, rej, min_area='400', max_aspect='1.0')

    k, _ = _run_filter(node, kept, rej, [
        _det((0, 0, 10, 10), name='tiny'),               # area 100 < 400
        _det((0, 0, 100, 20), name='wide'),              # aspect 5.0 > 1.0
        _det((0, 0, 30, 60), name='tall'),               # area 1800, aspect 0.5
    ])
    assert [d['class_name'] for d in k['detections']] == ['tall']


def test_filter_top_k(node_classes):
    kept, rej = node_classes['sink'](name='k'), node_classes['sink'](name='r')
    node = _filter(kept, rej, top_k='2')

    k, r = _run_filter(node, kept, rej, [
        _det((0, 0, 10, 10), conf=0.5, name='c'),
        _det((20, 0, 30, 10), conf=0.9, name='a'),
        _det((40, 0, 50, 10), conf=0.7, name='b'),
    ])
    assert sorted(d['class_name'] for d in k['detections']) == ['a', 'b']
    assert [d['class_name'] for d in r['detections']] == ['c']


def test_filter_nms_suppresses_overlaps(node_classes):
    kept, rej = node_classes['sink'](name='k'), node_classes['sink'](name='r')
    node = _filter(kept, rej, dedupe='nms', dedupe_threshold='0.5')

    k, r = _run_filter(node, kept, rej, [
        _det((100, 100, 200, 200), conf=0.9),
        _det((105, 105, 205, 205), conf=0.6),   # heavy overlap, same class
        _det((400, 100, 500, 200), conf=0.8),
    ])
    assert len(k['detections']) == 2
    assert k['detection_count'] == 2
    # NMS-suppressed duplicates are dropped, not routed to output 1
    assert r['detections'] == []


def test_filter_nmm_merges_overlaps(node_classes):
    kept, rej = node_classes['sink'](name='k'), node_classes['sink'](name='r')
    node = _filter(kept, rej, dedupe='nmm', dedupe_threshold='0.5')

    k, _ = _run_filter(node, kept, rej, [
        _det((100, 100, 200, 200), conf=0.9),
        _det((105, 105, 205, 205), conf=0.6),
    ])
    assert len(k['detections']) == 1


def test_filter_no_criteria_passes_everything(node_classes):
    kept, rej = node_classes['sink'](name='k'), node_classes['sink'](name='r')
    node = _filter(kept, rej)

    k, r = _run_filter(node, kept, rej, [_det((0, 0, 10, 10))])
    assert len(k['detections']) == 1 and r['detections'] == []


def test_filter_outputs_are_independent(node_classes):
    """Mutating the kept branch's payload must not leak into the rejected one."""
    kept, rej = node_classes['sink'](name='k'), node_classes['sink'](name='r')
    node = _filter(kept, rej, min_confidence='0.5')

    k, r = _run_filter(node, kept, rej, [
        _det((0, 0, 10, 10), conf=0.9, name='keep'),
        _det((20, 0, 30, 10), conf=0.1, name='drop'),
    ])
    k['detections'].append({'marker': True})
    assert all('marker' not in d for d in r['detections'])
    assert [d['class_name'] for d in r['detections']] == ['drop']


# --- sink ----------------------------------------------------------------

def _sink_node(sink, tmp_path, **config):
    node = SupervisionSinkNode(name='log')
    base = {'path': str(tmp_path), 'filename': 'test'}
    base.update(config)
    node.configure(base)
    node.connect(sink)
    return node


def test_csv_sink_writes_rows(node_classes, tmp_path):
    sink = node_classes['sink'](name='s')
    node = _sink_node(sink, tmp_path, format='csv')

    node.on_input({'payload': {'detections': [
        _det((10, 10, 50, 50), tid=1), _det((60, 10, 90, 50), tid=2, name='car', cid=2)]}})
    node.on_input({'payload': {'detections': []}})            # empty frame: no rows
    node.on_input({'payload': {'detections': [_det((12, 10, 52, 50), tid=1)]}})
    node.on_stop()

    out = sink.received[-1]['payload']
    assert out['sink_rows'] == 3
    assert out['sink_file'].endswith('.csv')

    with open(out['sink_file'], newline='') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    assert rows[0]['class_name'] == 'person' and rows[0]['tracker_id'] == '1'
    assert rows[1]['class_name'] == 'car'
    # empty frame advanced the frame counter without writing rows
    assert [r['frame'] for r in rows] == ['1', '1', '3']


def test_json_sink_written_on_stop(node_classes, tmp_path):
    sink = node_classes['sink'](name='s')
    node = _sink_node(sink, tmp_path, format='json')

    node.on_input({'payload': {'detections': [_det((10, 10, 50, 50), tid=1)]}})
    node.on_stop()

    path = sink.received[-1]['payload']['sink_file']
    data = json.load(open(path))
    assert len(data) == 1
    assert data[0]['class_name'] == 'person'


def test_sink_new_file_rotates(node_classes, tmp_path):
    sink = node_classes['sink'](name='s')
    node = _sink_node(sink, tmp_path, format='csv', filename='rot')

    node.on_input({'payload': {'detections': [_det((10, 10, 50, 50))]}})
    first = sink.received[-1]['payload']['sink_file']

    import time
    time.sleep(1.1)                     # timestamped names differ per second
    node.new_file()
    node.on_input({'payload': {'detections': [_det((10, 10, 50, 50))]}})
    second = sink.received[-1]['payload']['sink_file']
    node.on_stop()

    assert first != second
    assert sink.received[-1]['payload']['sink_rows'] == 1   # counter restarted


def test_sink_no_file_until_first_detection(node_classes, tmp_path):
    sink = node_classes['sink'](name='s')
    node = _sink_node(sink, tmp_path, format='csv')

    node.on_input({'payload': {'detections': []}})
    assert sink.received[-1]['payload']['sink_file'] is None
    assert list(tmp_path.iterdir()) == []
    node.on_stop()


def test_phase3_nodes_register_in_supervision_category():
    for cls in (SupervisionSmootherNode, SupervisionFilterNode, SupervisionSinkNode):
        assert cls.category == 'supervision'
    assert SupervisionFilterNode.output_count == 2
    assert 'new_file' in SupervisionSinkNode.actions
