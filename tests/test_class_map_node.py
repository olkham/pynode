"""Tests for ClassMapNode - relabelling detections by class id or name.

Nodes are driven directly (no Flask app / workflows dir); the node is wired to
the conftest 'sink' (synchronous on_input_direct delivery).
"""

import numpy as np
import pytest

from pynode.nodes.ClassMapNode.class_map_node import ClassMapNode, parse_class_map


# --- mapping syntax ---

@pytest.mark.parametrize('text', [
    '2 = drone\n1 = bird',
    '2: drone\n1: bird',
    '2 -> drone\n1 -> bird',
    '2, drone\n1, bird',
    '"2" = "drone"\n"1" = "bird"',
    "  2=drone  \n  1=bird  ",
    '{"2": "drone", "1": "bird"}',
    '# model C.7.S.3.1\n2 = drone\n\n1 = bird\n',
])
def test_mapping_spellings(text):
    mapping, problems = parse_class_map(text)

    assert mapping == {'2': 'drone', '1': 'bird'}
    assert problems == []


def test_mapping_accepts_a_dict():
    assert parse_class_map({2: 'drone'})[0] == {'2': 'drone'}


def test_mapping_empty_is_not_an_error():
    assert parse_class_map('') == ({}, [])


def test_mapping_reports_unreadable_lines():
    mapping, problems = parse_class_map('2 = drone\nnonsense\n1 = bird')

    assert mapping == {'2': 'drone', '1': 'bird'}
    assert problems == ['nonsense']


def test_mapping_reports_broken_json():
    mapping, problems = parse_class_map('{"2": drone}')

    assert mapping == {}
    assert len(problems) == 1 and 'JSON' in problems[0]


def test_mapping_value_may_contain_the_separator():
    assert parse_class_map('2 = drone, large')[0] == {'2': 'drone, large'}


def test_mapping_key_may_contain_spaces():
    assert parse_class_map('traffic light = signal')[0] == {'traffic light': 'signal'}


# --- the node ---

def _onnx_detections():
    """What InferenceNode emits for an ONNX model with no label file."""
    return [
        {'bbox': [0, 0, 10, 10], 'bbox_format': 'xyxy', 'top_class': 2,
         'class_id': 2, 'class_name': '2', 'confidence': 0.92},
        {'bbox': [20, 20, 30, 30], 'bbox_format': 'xyxy', 'top_class': 1,
         'class_id': 1, 'class_name': '1', 'confidence': 0.71},
    ]


def _run(sink, payload, **config):
    node = ClassMapNode(name='class map')
    node.configure(config)
    node.connect(sink)
    node.on_input({'payload': payload})
    return sink.received[-1]['payload']


def test_relabels_numeric_classes(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _onnx_detections(), 'detection_count': 2},
               mapping='2 = drone\n1 = bird')

    assert [d['class_name'] for d in out['detections']] == ['drone', 'bird']


def test_leaves_every_other_field_alone(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _onnx_detections()}, mapping='2 = drone')

    first = out['detections'][0]
    assert first['bbox'] == [0, 0, 10, 10]
    assert first['class_id'] == 2
    assert first['top_class'] == 2
    assert first['confidence'] == pytest.approx(0.92)


def test_does_not_mutate_the_incoming_detections(node_classes):
    """A branched message upstream must not see the relabelling."""
    sink = node_classes['sink'](name='sink')
    detections = _onnx_detections()
    _run(sink, {'detections': detections}, mapping='2 = drone')

    assert detections[0]['class_name'] == '2'


def test_matches_on_class_name(node_classes):
    sink = node_classes['sink'](name='sink')
    detections = [{'bbox': [0, 0, 1, 1], 'class_id': 0, 'class_name': 'Person'}]
    out = _run(sink, {'detections': detections}, mapping='person = human')

    assert out['detections'][0]['class_name'] == 'human'  # name match ignores case


def test_class_id_only_ignores_a_name_key(node_classes):
    sink = node_classes['sink'](name='sink')
    detections = [{'bbox': [0, 0, 1, 1], 'class_id': 0, 'class_name': 'person'}]
    out = _run(sink, {'detections': detections}, mapping='person = human', match_on='class_id')

    assert out['detections'][0]['class_name'] == 'person'


def test_class_id_wins_over_class_name_in_either_mode(node_classes):
    sink = node_classes['sink'](name='sink')
    detections = [{'bbox': [0, 0, 1, 1], 'class_id': 2, 'class_name': '1'}]
    out = _run(sink, {'detections': detections}, mapping='2 = drone\n1 = bird')

    assert out['detections'][0]['class_name'] == 'drone'


def test_unmatched_kept_by_default(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _onnx_detections()}, mapping='2 = drone')

    assert [d['class_name'] for d in out['detections']] == ['drone', '1']


def test_unmatched_relabelled_with_fallback(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _onnx_detections()},
               mapping='2 = drone', unmatched='label', unmatched_label='other')

    assert [d['class_name'] for d in out['detections']] == ['drone', 'other']


def test_unmatched_dropped_updates_the_count(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _onnx_detections(), 'detection_count': 2},
               mapping='2 = drone', unmatched='drop')

    assert [d['class_name'] for d in out['detections']] == ['drone']
    assert out['detection_count'] == 1


def test_custom_path_leaves_detection_count_alone(node_classes):
    """A node pointed at payload.tracks must not rewrite the detections count."""
    sink = node_classes['sink'](name='sink')
    out = _run(sink,
               {'tracks': _onnx_detections(), 'detections': [], 'detection_count': 7},
               mapping='2 = drone', unmatched='drop', detections_path='payload.tracks')

    assert [d['class_name'] for d in out['tracks']] == ['drone']
    assert out['detection_count'] == 7


def test_empty_mapping_passes_through(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _onnx_detections()}, mapping='')

    assert [d['class_name'] for d in out['detections']] == ['2', '1']


def test_missing_detections_list_passes_through(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'image': 'x'}, mapping='2 = drone')

    assert out == {'image': 'x'}


def test_non_dict_entries_survive(node_classes):
    sink = node_classes['sink'](name='sink')
    detections = [{'class_id': 2, 'class_name': '2'}, 'junk']
    out = _run(sink, {'detections': detections}, mapping='2 = drone')

    assert out['detections'][0]['class_name'] == 'drone'
    assert out['detections'][1] == 'junk'


def test_mapping_is_reparsed_when_the_config_changes(node_classes):
    sink = node_classes['sink'](name='sink')
    node = ClassMapNode(name='class map')
    node.configure({'mapping': '2 = drone'})
    node.connect(sink)

    node.on_input({'payload': {'detections': _onnx_detections()}})
    assert sink.received[-1]['payload']['detections'][0]['class_name'] == 'drone'

    node.configure({'mapping': '2 = quadcopter'})
    node.on_input({'payload': {'detections': _onnx_detections()}})
    assert sink.received[-1]['payload']['detections'][0]['class_name'] == 'quadcopter'


# --- supervision interop ---

def _sv_payload(sv):
    detections = sv.Detections(
        xyxy=np.array([[0., 0., 10., 10.], [20., 20., 30., 30.]]),
        confidence=np.array([0.92, 0.71]),
        class_id=np.array([2, 1]),
        data={'class_name': np.array(['2', '1'])},
    )
    return {
        'sv': detections,
        'detections': _onnx_detections(),
        'detection_count': 2,
    }


def test_syncs_labels_onto_the_live_sv_object(node_classes):
    sv = pytest.importorskip('supervision')
    sink = node_classes['sink'](name='sink')
    out = _run(sink, _sv_payload(sv), mapping='2 = drone\n1 = bird')

    assert list(out['sv'].data['class_name']) == ['drone', 'bird']


def test_dropping_filters_the_sv_object_too(node_classes):
    sv = pytest.importorskip('supervision')
    sink = node_classes['sink'](name='sink')
    out = _run(sink, _sv_payload(sv), mapping='2 = drone', unmatched='drop')

    assert len(out['sv']) == 1
    assert list(out['sv'].data['class_name']) == ['drone']
    assert list(out['sv'].class_id) == [2]


def test_sv_left_alone_when_it_does_not_match_the_list(node_classes):
    """Pointed at another list, the node must not pair labels with sv's boxes."""
    sv = pytest.importorskip('supervision')
    sink = node_classes['sink'](name='sink')
    payload = _sv_payload(sv)
    payload['tracks'] = [{'class_id': 2, 'class_name': '2'}]

    out = _run(sink, payload, mapping='2 = drone', detections_path='payload.tracks')

    assert out['tracks'][0]['class_name'] == 'drone'
    assert list(out['sv'].data['class_name']) == ['2', '1']
