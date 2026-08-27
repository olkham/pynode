"""Tests for ChangeNode, focused on list rules - applying a rule to a key
inside every object of a list (msg.payload.detections[*].class_name) - plus
regressions for the plain single-property behaviour.

Nodes are driven directly (no Flask app / workflows dir); the node is wired to
the conftest 'sink' (synchronous on_input_direct delivery).
"""

import pytest

from pynode.nodes.ChangeNode.change_node import ChangeNode


def _detections():
    """The shape InferenceNode emits for an ONNX model with no label file."""
    return [
        {'bbox': [0, 0, 10, 10], 'class_id': 2, 'class_name': '2', 'confidence': 0.63},
        {'bbox': [20, 20, 30, 30], 'class_id': 1, 'class_name': '1', 'confidence': 0.41},
    ]


def _run(sink, payload, *rules):
    node = ChangeNode(name='change')
    node.configure({'rules': list(rules)})
    node.connect(sink)
    node.on_input({'payload': payload})
    return sink.received[-1]['payload']


def _list_rule(**overrides):
    rule = {
        'type': 'change',
        'path': 'msg.payload.detections',
        'isList': True,
        'key': 'class_name',
        'search': '2',
        'replace': 'drone',
    }
    rule.update(overrides)
    return rule


# --- the reported use case ---

def test_change_replaces_the_key_in_every_item(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _detections(), 'detection_count': 2}, _list_rule())

    assert [d['class_name'] for d in out['detections']] == ['drone', '1']


def test_two_rules_relabel_two_classes(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _detections()},
               _list_rule(search='2', replace='drone'),
               _list_rule(search='1', replace='bird'))

    assert [d['class_name'] for d in out['detections']] == ['drone', 'bird']


def test_other_fields_are_untouched(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _detections()}, _list_rule())

    first = out['detections'][0]
    assert first['bbox'] == [0, 0, 10, 10]
    assert first['class_id'] == 2
    assert first['confidence'] == pytest.approx(0.63)


def test_snake_case_alias_is_accepted(node_classes):
    sink = node_classes['sink'](name='sink')
    rule = _list_rule()
    rule['is_list'] = rule.pop('isList')
    out = _run(sink, {'detections': _detections()}, rule)

    assert out['detections'][0]['class_name'] == 'drone'


# --- list mode across the other operations ---

def test_set_writes_the_key_on_every_item(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _detections()},
               _list_rule(type='set', key='source', value='camera-1', valueType='str'))

    assert [d['source'] for d in out['detections']] == ['camera-1', 'camera-1']


def test_set_with_a_typed_value(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _detections()},
               _list_rule(type='set', key='priority', value='3', valueType='num'))

    assert [d['priority'] for d in out['detections']] == [3, 3]


def test_delete_removes_the_key_from_every_item(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _detections()}, _list_rule(type='delete', key='confidence'))

    assert all('confidence' not in d for d in out['detections'])
    assert all('class_name' in d for d in out['detections'])


def test_move_renames_the_key_within_each_item(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _detections()},
               _list_rule(type='move', key='class_name', toPath='label'))

    assert [d['label'] for d in out['detections']] == ['2', '1']
    assert all('class_name' not in d for d in out['detections'])


# --- search semantics ---

def test_regex_search_can_anchor_the_whole_value(node_classes):
    """'2' as a substring would also hit '12'; ^2$ does not."""
    sink = node_classes['sink'](name='sink')
    detections = [{'class_name': '2'}, {'class_name': '12'}]
    out = _run(sink, {'detections': detections},
               _list_rule(search='^2$', searchType='regex', replace='drone'))

    assert [d['class_name'] for d in out['detections']] == ['drone', '12']


def test_substring_replace_is_the_default(node_classes):
    sink = node_classes['sink'](name='sink')
    detections = [{'class_name': 'big drone'}]
    out = _run(sink, {'detections': detections},
               _list_rule(search='drone', replace='quadcopter'))

    assert out['detections'][0]['class_name'] == 'big quadcopter'


def test_numeric_value_replaced_on_whole_match(node_classes):
    """class_id is an int - there is no substring, so the search must match it."""
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _detections()},
               _list_rule(key='class_id', search='2', replace='7', replaceType='num'))

    assert [d['class_id'] for d in out['detections']] == [7, 1]


def test_numeric_value_not_replaced_on_partial_match(node_classes):
    sink = node_classes['sink'](name='sink')
    detections = [{'class_id': 12}]
    out = _run(sink, {'detections': detections},
               _list_rule(key='class_id', search='2', replace='7', replaceType='num'))

    assert out['detections'][0]['class_id'] == 12


def test_missing_key_on_an_item_is_skipped(node_classes):
    sink = node_classes['sink'](name='sink')
    detections = [{'class_name': '2'}, {'bbox': [0, 0, 1, 1]}]
    out = _run(sink, {'detections': detections}, _list_rule())

    assert out['detections'][0]['class_name'] == 'drone'
    assert 'class_name' not in out['detections'][1]


def test_non_dict_items_are_skipped(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': [{'class_name': '2'}, 'junk', 7]}, _list_rule())

    assert out['detections'][0]['class_name'] == 'drone'
    assert out['detections'][1:] == ['junk', 7]


# --- misconfiguration stays harmless ---

def test_list_rule_without_a_key_passes_the_message_through(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': _detections()}, _list_rule(key=''))

    assert [d['class_name'] for d in out['detections']] == ['2', '1']


def test_list_rule_on_a_non_list_passes_the_message_through(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': 'not a list'}, _list_rule())

    assert out['detections'] == 'not a list'


def test_list_rule_on_a_missing_path_passes_the_message_through(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'image': 'x'}, _list_rule())

    assert out == {'image': 'x'}


def test_empty_list_is_a_no_op(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'detections': [], 'detection_count': 0}, _list_rule())

    assert out['detections'] == []


# --- regressions: plain single-property rules still behave ---

def test_set_scalar_property(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'value': 1},
               {'type': 'set', 'path': 'msg.payload.value', 'value': '42', 'valueType': 'num'})

    assert out['value'] == 42


def test_change_scalar_property(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'text': 'hello world'},
               {'type': 'change', 'path': 'msg.payload.text', 'search': 'world', 'replace': 'there'})

    assert out['text'] == 'hello there'


def test_change_scalar_regex(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'text': 'abc123'},
               {'type': 'change', 'path': 'msg.payload.text', 'search': r'\d+',
                'searchType': 'regex', 'replace': '#'})

    assert out['text'] == 'abc#'


def test_change_with_an_empty_replacement_clears_the_match(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'text': 'hello world'},
               {'type': 'change', 'path': 'msg.payload.text', 'search': ' world', 'replace': ''})

    assert out['text'] == 'hello'


def test_delete_scalar_property(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'a': 1, 'b': 2}, {'type': 'delete', 'path': 'msg.payload.a'})

    assert out == {'b': 2}


def test_move_scalar_property(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'a': 1}, {'type': 'move', 'path': 'msg.payload.a', 'toPath': 'msg.payload.b'})

    assert out == {'b': 1}


def test_rules_apply_in_order(node_classes):
    sink = node_classes['sink'](name='sink')
    out = _run(sink, {'text': 'a'},
               {'type': 'change', 'path': 'msg.payload.text', 'search': 'a', 'replace': 'b'},
               {'type': 'change', 'path': 'msg.payload.text', 'search': 'b', 'replace': 'c'})

    assert out['text'] == 'c'
