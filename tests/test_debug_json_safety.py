"""Debug entries must always be JSON-serializable.

Regression for the supervision integration: a live ``sv.Detections`` at
``payload.sv`` (short repr) used to pass through DebugNode's truncation as a
raw object. ``json.dumps`` then raised inside the SSE generator, closing the
stream that carries ALL live UI updates - debug messages AND image-viewer
frames - which surfaced as viewers going dark whenever tracker output reached
a Debug node.

DebugNode is driven directly - no Flask app, no workflows dir, no threads.
"""

import json

import numpy as np
import pytest

from pynode.nodes.DebugNode.debug_node import DebugNode


def _entry_for(payload):
    node = DebugNode(name='dbg')
    node.configure({'console': False, 'complete': 'payload'})
    node.on_input({'payload': payload, 'topic': 't'})
    assert node.messages, "debug node stored no entry"
    return node.messages[-1]


def test_numpy_scalars_serialize():
    entry = _entry_for({'value': np.float32(0.25), 'count': np.int64(3),
                        'flag': np.bool_(True)})
    dumped = json.loads(json.dumps(entry))
    assert dumped['output']['value'] == pytest.approx(0.25)
    assert dumped['output']['count'] == 3
    assert dumped['output']['flag'] is True


def test_numpy_image_summarised():
    entry = _entry_for({'image': np.zeros((480, 640, 3), np.uint8)})
    json.dumps(entry)
    assert 'numpy array' in entry['output']['image']


def test_arbitrary_object_is_stringified():
    class Weird:
        def __repr__(self):
            return '<weird object>'

    entry = _entry_for({'thing': Weird()})
    json.dumps(entry)
    assert entry['output']['thing'] == '<weird object>'


def test_tuple_payload_serialises():
    entry = _entry_for({'point': (4, 5)})
    assert json.loads(json.dumps(entry))['output']['point'] == [4, 5]


def test_supervision_payload_serialises():
    """The exact poisoning case: a tracked payload including payload.sv."""
    sv = pytest.importorskip('supervision')
    from pynode.nodes.Supervision.supervision_tracker_node import SupervisionTrackerNode
    from pynode.nodes.base_node import BaseNode

    class Sink(BaseNode):
        input_count, output_count = 1, 0

        def __init__(self, **kw):
            super().__init__(**kw)
            self.got = []

        def on_input_direct(self, msg, i=0):
            self.got.append(msg)

    sink = Sink(name='s')
    tracker = SupervisionTrackerNode(name='t')
    tracker.connect(sink)

    # One frame with a detection, one with none (empty Detections has a SHORT
    # repr - the original failure mode).
    tracker.on_input({'payload': {'detections': [
        {'bbox': [10, 10, 60, 90], 'class_id': 0, 'class_name': 'person',
         'confidence': 0.9}]}})
    tracker.on_input({'payload': {'detections': []}})

    for msg in sink.got:
        entry = _entry_for(msg['payload'])
        json.dumps(entry)                     # must not raise
        assert 'Detections' in entry['output']['sv']  # stringified, not raw
