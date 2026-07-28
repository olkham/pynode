"""Tests for FunctionNode - the msg.payload attribute-access support (DotDict)
and the built-in code examples.

Nodes are driven directly (no Flask app / workflows dir, no worker threads);
the node is wired to the conftest 'sink' (synchronous on_input_direct delivery),
so nothing here can leak a thread or touch the real workflows/ directory.
"""

import copy

import numpy as np
import pytest

from pynode.nodes.FunctionNode.function_node import (
    FunctionNode,
    DotDict,
    _to_dotdict,
    FUNCTION_EXAMPLES,
)


def _make(sink, func, **config):
    node = FunctionNode(name='func')
    node.configure({'func': func, **config})
    node.connect(sink)
    return node


def _run(sink, node, msg):
    node.on_input(msg)
    return sink.received[-1] if sink.received else None


# --- attribute style (msg.payload) vs dictionary style (msg['payload']) ------

def test_attribute_style_read_write(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, 'msg.payload = int(msg.payload)\nreturn msg')
    out = _run(sink, node, {'payload': '42'})
    assert out['payload'] == 42


def test_dictionary_style_still_works(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, "msg['payload'] = msg['payload'] * 2\nreturn msg")
    out = _run(sink, node, {'payload': 5})
    assert out['payload'] == 10


def test_set_topic_via_attribute(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, "msg.topic = 'hello'\nreturn msg")
    out = _run(sink, node, {'payload': 1})
    assert out['topic'] == 'hello'


def test_nested_attribute_read(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, 'msg.payload = msg.payload.bbox\nreturn msg')
    out = _run(sink, node, {'payload': {'bbox': [1, 2, 3, 4], 'x': 9}})
    assert out['payload'] == [1, 2, 3, 4]


def test_nested_attribute_write(node_classes):
    sink = node_classes['sink'](name='sink')
    # writes through the chained path, same target as msg['payload']['crop']
    node = _make(sink, 'msg.payload.crop = msg.payload.crop[0]\nreturn msg')
    out = _run(sink, node, {'payload': {'crop': [7, 8, 9]}})
    assert out['payload']['crop'] == 7


# --- payload/message integrity ----------------------------------------------

def test_numpy_payload_passthrough(node_classes):
    sink = node_classes['sink'](name='sink')
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    node = _make(sink, 'return msg')
    out = _run(sink, node, {'payload': img})
    assert isinstance(out['payload'], np.ndarray)
    assert out['payload'].shape == (4, 4, 3)


def test_original_msg_not_mutated(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, "msg.payload['a'] = 99\nreturn msg")
    original = {'payload': {'a': 1}}
    node.on_input(original)
    assert original['payload']['a'] == 1          # caller's message untouched
    assert sink.received[-1]['payload']['a'] == 99


def test_return_none_drops_message(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, 'if msg.payload < 10:\n    return None\nreturn msg')
    node.on_input({'payload': 3})
    assert sink.received == []                     # dropped, nothing sent
    node.on_input({'payload': 20})
    assert sink.received[-1]['payload'] == 20


def test_node_state_persists_between_messages(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(
        sink,
        'node.count = getattr(node, "count", 0) + 1\n'
        'msg.payload = node.count\nreturn msg',
    )
    node.on_input({'payload': 0})
    node.on_input({'payload': 0})
    assert [m['payload'] for m in sink.received] == [1, 2]


def test_multiple_outputs(node_classes):
    sink0 = node_classes['sink'](name='s0')
    sink1 = node_classes['sink'](name='s1')
    node = FunctionNode(name='func')
    node.configure({'func': "return [msg, {'payload': 'copy'}]", 'outputs': 2})
    node.connect(sink0, 0)
    node.connect(sink1, 1)
    node.on_input({'payload': 'orig'})
    assert sink0.received[-1]['payload'] == 'orig'
    assert sink1.received[-1]['payload'] == 'copy'


# --- DotDict unit behavior ---------------------------------------------------

def test_dotdict_basic():
    d = DotDict({'a': 1})
    assert d.a == 1 and d['a'] == 1
    d.b = 2
    assert d['b'] == 2 and d.b == 2
    del d.b
    assert 'b' not in d
    with pytest.raises(AttributeError):
        _ = d.missing


def test_dotdict_method_keys_not_shadowed():
    # A key colliding with a dict method stays reachable via item access;
    # attribute access returns the method (documented limitation).
    d = DotDict({'items': [1, 2]})
    assert d['items'] == [1, 2]
    assert callable(d.items)


def test_to_dotdict_recursive_and_deepcopy():
    src = {'payload': {'crop': [{'x': 1}]}, 'n': 5}
    dd = _to_dotdict(src)
    assert dd.payload.crop[0].x == 1
    assert type(src['payload']) is dict            # source not converted...
    src['payload']['crop'][0]['x'] = 2
    assert dd.payload.crop[0].x == 1               # ...or mutated

    # deepcopy (the send() fan-out path) must preserve DotDict + attr access
    cp = copy.deepcopy(dd)
    assert isinstance(cp, DotDict)
    assert cp.payload.crop[0].x == 1


# --- the shipped examples all parse / execute -------------------------------

@pytest.mark.parametrize('ex', FUNCTION_EXAMPLES, ids=lambda e: e['label'])
def test_examples_compile(ex):
    body = ex['code']
    wrapped = 'def f(msg, node, time):\n' + '\n'.join(
        '    ' + line for line in body.split('\n')
    )
    compile(wrapped, '<example>', 'exec')          # raises on bad indentation/syntax


@pytest.mark.parametrize('ex', FUNCTION_EXAMPLES, ids=lambda e: e['label'])
def test_examples_declare_output_count(ex):
    # The UI applies 'outputs' to the node when an example is picked, so every
    # example must state one within the property's 1..10 range.
    assert isinstance(ex['outputs'], int)
    assert 1 <= ex['outputs'] <= 10


def test_example_code_and_labels_unique():
    # The dropdown derives its selection by matching the editor's code against
    # these snippets; duplicates would make the wrong entry appear selected.
    codes = [ex['code'] for ex in FUNCTION_EXAMPLES]
    labels = [ex['label'] for ex in FUNCTION_EXAMPLES]
    assert len(set(codes)) == len(codes)
    assert len(set(labels)) == len(labels)


def test_multi_output_examples_use_their_outputs(node_classes):
    # Each example declaring outputs=2 must actually drive both ports.
    for ex in [e for e in FUNCTION_EXAMPLES if e['outputs'] == 2]:
        sinks = [node_classes['sink'](name=f's{i}') for i in range(2)]
        node = FunctionNode(name='func')
        node.configure({'func': ex['code'], 'outputs': ex['outputs']})
        for i, s in enumerate(sinks):
            node.connect(s, i)
        assert node.output_count == 2
        # Drive with values on both sides of any threshold in the snippet.
        node.on_input({'payload': 500})
        node.on_input({'payload': 1})
        assert any(s.received for s in sinks), ex['label']
