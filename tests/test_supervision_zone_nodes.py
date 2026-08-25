"""Tests for SupervisionLineCounterNode and SupervisionZoneNode.

Driven directly via ``on_input`` wired to conftest sinks - no Flask app, no
workflows dir, no worker threads, nothing touching real workflow data.
"""

import json

import numpy as np
import pytest

sv = pytest.importorskip('supervision')

from pynode.nodes.Supervision.supervision_line_counter_node import (  # noqa: E402
    SupervisionLineCounterNode,
)
from pynode.nodes.Supervision.supervision_zone_node import (  # noqa: E402
    SupervisionZoneNode,
)
from pynode.nodes.supervision_utils import parse_line, parse_points  # noqa: E402


def _img(h=480, w=640):
    return np.full((h, w, 3), 30, np.uint8)


def _det(bbox, tid=1, cid=0, name='person', conf=0.9):
    return {'bbox': list(bbox), 'class_id': cid, 'class_name': name,
            'confidence': conf, 'track_id': tid}


def _wire(node_cls, main_sink, event_sink, **config):
    node = node_cls(name='zone')
    if config:
        node.configure(config)
    node.connect(main_sink, output_index=0)
    node.connect(event_sink, output_index=1)
    return node


# --- parse helpers -------------------------------------------------------

@pytest.mark.parametrize('raw,expected', [
    ('160,240,480,240', ((160.0, 240.0), (480.0, 240.0))),
    ('[[160,240],[480,240]]', ((160.0, 240.0), (480.0, 240.0))),
    ([[1, 2], [3, 4]], ((1.0, 2.0), (3.0, 4.0))),
    ('garbage', None),
    ('1,2,3', None),
    ('', None),
])
def test_parse_line(raw, expected):
    assert parse_line(raw) == expected


@pytest.mark.parametrize('raw,valid', [
    ('[[0,0],[100,0],[100,100]]', True),
    ('0,0,100,0,100,100', True),
    ([[0, 0], [100, 0], [100, 100], [0, 100]], True),
    ('[[0,0],[100,0]]', False),      # only 2 points
    ('nonsense', False),
    ('', False),
])
def test_parse_points(raw, valid):
    assert (parse_points(raw) is not None) is valid


# --- line counter --------------------------------------------------------

def _cross_line(node, sinks, direction='down'):
    """Move one tracked box across the horizontal line at y=240."""
    ys = (140.0, 200.0, 280.0, 340.0) if direction == 'down' else (340.0, 280.0, 200.0, 140.0)
    for y in ys:
        node.on_input({'payload': {
            'detections': [_det((300, y, 340, y + 40))]}})


def test_line_crossing_counts_and_event(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionLineCounterNode, main, events,
                 line='160,240,480,240', draw='false')

    _cross_line(node, (main, events))

    out = main.received[-1]['payload']
    assert out['line_in'] + out['line_out'] == 1
    assert len(events.received) == 1
    ev = events.received[-1]['payload']
    assert ev['event'] == 'line_crossing'
    assert ev['track_id'] == 1
    assert ev['class_name'] == 'person'
    assert ev['direction'] in ('in', 'out')
    # per-class-name counters accumulated
    by_class = out['line_in_by_class'] if out['line_in'] else out['line_out_by_class']
    assert by_class == {'person': 1}


def test_no_event_without_crossing(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionLineCounterNode, main, events,
                 line='160,240,480,240', draw='false')

    for y in (100.0, 120.0, 140.0):   # stays above the line
        node.on_input({'payload': {'detections': [_det((300, y, 340, y + 40))]}})

    assert not events.received
    assert main.received[-1]['payload']['line_in'] == 0
    assert main.received[-1]['payload']['line_out'] == 0


def test_untracked_detections_warn_once_and_pass_through(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionLineCounterNode, main, events, draw='false')

    errors = []
    node.report_error = lambda m: errors.append(m)

    det = {'bbox': [300, 100, 340, 140], 'class_id': 0,
           'class_name': 'person', 'confidence': 0.9}   # no track_id
    node.on_input({'payload': {'detections': [det]}})
    node.on_input({'payload': {'detections': [det]}})

    assert len(main.received) == 2      # still flowing
    assert len(errors) == 1
    assert 'Tracker' in errors[0]


def test_reset_zeroes_counts(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionLineCounterNode, main, events,
                 line='160,240,480,240', draw='false')

    _cross_line(node, (main, events))
    assert main.received[-1]['payload']['line_in'] + \
        main.received[-1]['payload']['line_out'] == 1

    node.reset()
    node.on_input({'payload': {'detections': []}})

    out = main.received[-1]['payload']
    assert out['line_in'] == 0 and out['line_out'] == 0
    assert out['line_in_by_class'] == {} and out['line_out_by_class'] == {}


def test_set_geometry_applies_live_and_resets(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionLineCounterNode, main, events,
                 line='160,240,480,240', draw='false')
    _cross_line(node, (main, events))

    node.set_geometry('0,100,640,100')

    assert node.config['line'] == '0,100,640,100'
    node.on_input({'payload': {'detections': []}})
    assert main.received[-1]['payload']['line_in'] == 0


def test_reconfigure_same_line_keeps_counts(node_classes):
    """Editing an unrelated property must not zero the counters."""
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionLineCounterNode, main, events,
                 line='160,240,480,240', draw='false')
    _cross_line(node, (main, events))
    total = main.received[-1]['payload']['line_in'] + \
        main.received[-1]['payload']['line_out']

    node.configure({'draw': 'true'})
    node.configure({'draw': 'false'})
    node.on_input({'payload': {'detections': []}})

    out = main.received[-1]['payload']
    assert out['line_in'] + out['line_out'] == total == 1


def test_line_draw_annotates_frame(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionLineCounterNode, main, events,
                 line='160,240,480,240', draw='true')

    image = _img()
    node.on_input({'payload': {'image': image,
                               'detections': [_det((300, 100, 340, 140))]}})

    out = main.received[-1]['payload']
    assert (out['image'] != 30).any()
    assert not (image != 30).any()      # input frame untouched


def test_editor_frame_route(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionLineCounterNode, main, events, draw='false')

    assert node.get_editor_frame() == {'data': None}

    node.on_input({'payload': {'image': _img(h=120, w=160), 'detections': []}})
    frame = node.get_editor_frame()
    assert frame['width'] == 160 and frame['height'] == 120
    assert isinstance(frame['data'], str) and len(frame['data']) > 100
    json.dumps(frame)   # JSON-safe for the api route


# --- polygon zone --------------------------------------------------------

ZONE = '[[100,100],[500,100],[500,400],[100,400]]'


def test_zone_counts_and_flags(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionZoneNode, main, events, polygon=ZONE, draw='false')

    node.on_input({'payload': {'detections': [
        _det((200, 200, 260, 340), tid=1),          # feet (230,340) inside
        _det((520, 200, 580, 340), tid=2),          # feet (550,340) outside
    ]}})

    out = main.received[-1]['payload']
    assert out['zone_count'] == 1
    assert [d['in_zone'] for d in out['detections']] == [True, False]


def test_zone_enter_exit_events(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionZoneNode, main, events, polygon=ZONE, draw='false')

    # outside -> inside -> outside (same track)
    node.on_input({'payload': {'detections': [_det((520, 200, 580, 340))]}})
    node.on_input({'payload': {'detections': [_det((200, 200, 260, 340))]}})
    node.on_input({'payload': {'detections': [_det((520, 200, 580, 340))]}})

    kinds = [m['payload']['event'] for m in events.received]
    assert kinds == ['enter', 'exit']
    assert events.received[0]['payload']['track_id'] == 1
    assert events.received[0]['payload']['class_name'] == 'person'


def test_zone_no_events_without_track_ids(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionZoneNode, main, events, polygon=ZONE, draw='false')

    det = {'bbox': [200, 200, 260, 340], 'class_id': 0,
           'class_name': 'person', 'confidence': 0.9}    # no track_id
    node.on_input({'payload': {'detections': [det]}})

    assert not events.received
    # counting still works positionally
    assert main.received[-1]['payload']['zone_count'] == 1


def test_zone_filter_to_zone(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionZoneNode, main, events, polygon=ZONE,
                 filter_to_zone=True, draw='false')

    node.on_input({'payload': {'detections': [
        _det((200, 200, 260, 340), tid=1),
        _det((520, 200, 580, 340), tid=2),
    ]}})

    out = main.received[-1]['payload']
    assert out['zone_count'] == 1
    assert len(out['detections']) == 1
    assert out['detections'][0]['track_id'] == 1
    assert out['detections'][0]['in_zone'] is True


def test_zone_draw_annotates_frame(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionZoneNode, main, events, polygon=ZONE, draw='true')

    image = _img()
    node.on_input({'payload': {'image': image, 'detections': []}})

    assert (main.received[-1]['payload']['image'] != 30).any()


def test_zone_set_geometry_live(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionZoneNode, main, events, polygon=ZONE, draw='false')

    node.on_input({'payload': {'detections': [_det((200, 200, 260, 340))]}})
    assert main.received[-1]['payload']['zone_count'] == 1

    # shrink the zone so the same box lands outside
    node.set_geometry('[[0,0],[50,0],[50,50],[0,50]]')
    node.on_input({'payload': {'detections': [_det((200, 200, 260, 340))]}})
    assert main.received[-1]['payload']['zone_count'] == 0


def test_invalid_polygon_reports_and_passes_through(node_classes):
    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionZoneNode, main, events, polygon='junk', draw='false')

    errors = []
    node.report_error = lambda m: errors.append(m)

    node.on_input({'payload': {'detections': [_det((200, 200, 260, 340))]}})

    assert len(main.received) == 1          # passed through
    assert any('Invalid polygon' in e for e in errors)


def test_zone_payload_stays_json_safe(node_classes):
    """Zone outputs feed the debug panel - keep them strictly serializable."""
    from pynode.nodes.DebugNode.debug_node import DebugNode

    main, events = node_classes['sink'](name='m'), node_classes['sink'](name='e')
    node = _wire(SupervisionZoneNode, main, events, polygon=ZONE, draw='false')
    node.on_input({'payload': {'detections': [_det((200, 200, 260, 340))]}})

    dbg = DebugNode(name='dbg')
    dbg.configure({'console': False, 'complete': 'payload'})
    dbg.on_input(main.received[-1])
    json.dumps(dbg.messages[-1])

    for msg in events.received:
        json.dumps(msg['payload'])


def test_nodes_register_in_supervision_category():
    assert SupervisionLineCounterNode.category == 'supervision'
    assert SupervisionZoneNode.category == 'supervision'
    for cls in (SupervisionLineCounterNode, SupervisionZoneNode):
        assert cls.output_count == 2
        assert 'reset' in cls.actions and 'set_geometry' in cls.actions
