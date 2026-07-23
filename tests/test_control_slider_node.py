"""Tests for ControlSliderNode - the interactive value-slider control.

Safety: nodes are driven directly (no Flask app / workflows dir). Any node
started with on_start() is stopped in a try/finally before the test returns.
"""

import time

from pynode.nodes.ControlSliderNode.control_slider_node import ControlSliderNode


def _wait_until(predicate, timeout=5.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _make(sink, **config):
    node = ControlSliderNode(name='slider')
    cfg = {'path': 'payload.value', 'min': 0, 'max': 1, 'step': 0.01, 'value': 0.5}
    cfg.update(config)
    node.configure(cfg)
    node.connect(sink)
    return node


def test_registers_as_slider_component():
    assert ControlSliderNode.ui_component == 'slider'
    assert ControlSliderNode.input_count == 1 and ControlSliderNode.output_count == 1
    assert 'set_value' in ControlSliderNode.actions


def test_stamps_config_value_and_forwards(node_classes):
    """on_input writes the value to the path and forwards the message."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink, value=0.42)
    node.on_input({'payload': {'image': 'IMG'}})
    got = sink.received[-1]
    assert got['payload']['value'] == 0.42
    assert got['payload']['image'] == 'IMG'  # rest of the message preserved


def test_creates_missing_path(node_classes):
    """Intermediate objects/lists are created when the path doesn't exist."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink, path='payload.crop.x', value=0.3)
    node.on_input({'payload': {}})
    assert sink.received[-1]['payload']['crop']['x'] == 0.3


def test_set_value_is_live_on_next_message(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, value=0.1)
    node.on_input({'payload': {}})
    assert sink.received[-1]['payload']['value'] == 0.1
    node.set_value(0.9)  # user drags the slider
    node.on_input({'payload': {}})
    assert sink.received[-1]['payload']['value'] == 0.9


def test_clamps_to_range(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min=0, max=1)
    node.set_value(5.0)
    node.on_input({'payload': {}})
    assert sink.received[-1]['payload']['value'] == 1
    node.set_value(-3.0)
    node.on_input({'payload': {}})
    assert sink.received[-1]['payload']['value'] == 0


def test_swapped_min_max_still_clamps(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, min=1, max=0)  # user entered them backwards
    node.set_value(0.5)
    node.on_input({'payload': {}})
    assert sink.received[-1]['payload']['value'] == 0.5
    node.set_value(2.0)
    node.on_input({'payload': {}})
    assert sink.received[-1]['payload']['value'] == 1


def test_integer_step_emits_int(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, path='payload.width', min=0, max=200, step=1)
    node.set_value(120.0)
    node.on_input({'payload': {}})
    val = sink.received[-1]['payload']['width']
    assert val == 120 and isinstance(val, int)


def test_fractional_value_stays_float(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, value=0.25)
    node.on_input({'payload': {}})
    val = sink.received[-1]['payload']['value']
    assert val == 0.25 and isinstance(val, float)


def test_on_start_seeds_live_value_from_config(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, value=0.7)
    node.on_start()
    try:
        node.on_input({'payload': {}})
        assert sink.received[-1]['payload']['value'] == 0.7
    finally:
        node.on_stop()


def test_empty_path_passes_through(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, path='')
    node.on_input({'payload': {'a': 1}})
    assert sink.received[-1]['payload'] == {'a': 1}


def test_bad_path_reports_and_still_forwards(node_classes):
    """A path incompatible with the payload reports an error but still
    forwards the message (control never silently swallows frames)."""
    errors = []
    sink = node_classes['sink'](name='sink')
    node = _make(sink, path='payload.x.y')  # payload.x is a string, can't nest
    node.report_error = lambda m: errors.append(m)
    node.on_input({'payload': {'x': 'not-a-dict'}})
    assert len(sink.received) == 1        # forwarded
    assert errors                          # and reported


def test_send_on_change_off_emits_nothing(node_classes):
    """Default: moving the slider does not emit on its own (only on_input does)."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink)  # send_on_change defaults off
    node.set_value(0.3)
    node.set_value(0.6)
    assert sink.received == []


def test_send_on_change_emits_value_message(node_classes):
    """With send_on_change on, each move emits a fresh message with the value
    at the target path - no input required."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink, path='payload.threshold', send_on_change=True)
    node.set_value(0.3)
    assert len(sink.received) == 1
    assert sink.received[-1]['payload']['threshold'] == 0.3
    node.set_value(0.8)  # dragging again emits again
    assert len(sink.received) == 2
    assert sink.received[-1]['payload']['threshold'] == 0.8


def test_send_on_change_empty_path_sets_payload(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, path='', send_on_change=True)
    node.set_value(0.42)
    assert sink.received[-1]['payload'] == 0.42


def test_send_on_change_still_forwards_input(node_classes):
    """send_on_change does not disable the passthrough path: an incoming
    message is still stamped and forwarded independently of change-emits."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink, path='payload.v', send_on_change=True)
    node.set_value(0.5)                     # 1 emit
    node.on_input({'payload': {'img': 'X'}})  # stamped + forwarded
    assert len(sink.received) == 2
    assert sink.received[-1]['payload']['v'] == 0.5
    assert sink.received[-1]['payload']['img'] == 'X'


def test_daisy_chain_builds_bbox(node_classes):
    """Four sliders in series each set one bbox index -> a full crop box,
    exactly the crop-control use case. Uses the real queued send path."""
    sink = node_classes['sink'](name='sink')
    s4 = _make(sink, path='payload.detections[0].bbox[3]', value=0.8)
    s3 = ControlSliderNode(name='s3')
    s3.configure({'path': 'payload.detections[0].bbox[2]', 'min': 0, 'max': 1, 'value': 0.7})
    s3.connect(s4)
    s2 = ControlSliderNode(name='s2')
    s2.configure({'path': 'payload.detections[0].bbox[1]', 'min': 0, 'max': 1, 'value': 0.2})
    s2.connect(s3)
    s1 = ControlSliderNode(name='s1')
    s1.configure({'path': 'payload.detections[0].bbox[0]', 'min': 0, 'max': 1, 'value': 0.1})
    s1.connect(s2)
    # Start the middle nodes' workers (they receive via the queued path).
    for n in (s2, s3, s4):
        n.on_start()
    try:
        s1.on_input({'payload': {'image': 'IMG'}})
        assert _wait_until(lambda: len(sink.received) == 1)
        bbox = sink.received[-1]['payload']['detections'][0]['bbox']
        assert bbox == [0.1, 0.2, 0.7, 0.8]
        assert sink.received[-1]['payload']['image'] == 'IMG'
    finally:
        for n in (s2, s3, s4):
            n.on_stop()
