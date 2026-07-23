"""Tests for CropNode - focused on the custom-path bbox source (format/space
selectors) plus regressions for detections/manual and numpy-image output.

Nodes are driven directly (no Flask app / workflows dir); the node is wired to
the conftest 'sink' (synchronous on_input_direct delivery).
"""

import numpy as np
import pytest

from pynode.nodes.CropNode.crop_node import CropNode


def _img(h=480, w=640):
    """A raw BGR numpy image (the default frame format in PyNode)."""
    a = np.zeros((h, w, 3), dtype=np.uint8)
    a[:, :, 1] = 128  # non-black so the crop is visibly valid
    return a


def _make(sink, **config):
    node = CropNode(name='crop')
    node.configure(config)
    node.connect(sink)
    return node


def _run(sink, node, payload):
    node.on_input({'payload': payload})
    return sink.received[-1]['payload'] if sink.received else None


# --- custom path mode: formats all describe the SAME box -> [64,96,384,336] ---

@pytest.mark.parametrize('fmt,coords', [
    ('x1y1x2y2', [0.1, 0.2, 0.6, 0.7]),
    ('xywh',     [0.1, 0.2, 0.5, 0.5]),
    ('x1x2y1y2', [0.1, 0.6, 0.2, 0.7]),
    ('cxcywh',   [0.35, 0.45, 0.5, 0.5]),
])
def test_path_formats_normalized(node_classes, fmt, coords):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, bbox_source='path', bbox_path='payload.crop',
                 bbox_format=fmt, bbox_space='normalized')
    out = _run(sink, node, {'image': _img(), 'crop': coords})
    assert out['bbox'] == [64, 96, 384, 336]
    assert out['image'].shape == (240, 320, 3)  # cropped region


def test_path_absolute_space(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, bbox_source='path', bbox_path='payload.crop',
                 bbox_format='x1y1x2y2', bbox_space='absolute')
    out = _run(sink, node, {'image': _img(), 'crop': [64, 96, 384, 336]})
    assert out['bbox'] == [64, 96, 384, 336]


def test_path_absolute_xywh(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, bbox_source='path', bbox_path='payload.crop',
                 bbox_format='xywh', bbox_space='absolute')
    out = _run(sink, node, {'image': _img(), 'crop': [64, 96, 320, 240]})
    assert out['bbox'] == [64, 96, 384, 336]


def test_path_dict_input(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, bbox_source='path', bbox_path='payload.crop',
                 bbox_format='xywh', bbox_space='normalized')
    out = _run(sink, node, {'image': _img(), 'crop': {'x': 0.1, 'y': 0.2, 'w': 0.5, 'h': 0.5}})
    assert out['bbox'] == [64, 96, 384, 336]


def test_path_custom_location(node_classes):
    """The path can point anywhere, e.g. a nested key or list index."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink, bbox_source='path', bbox_path='payload.roi.box',
                 bbox_format='x1y1x2y2', bbox_space='normalized')
    out = _run(sink, node, {'image': _img(), 'roi': {'box': [0.1, 0.2, 0.6, 0.7]}})
    assert out['bbox'] == [64, 96, 384, 336]


def test_path_reversed_corners_sorted(node_classes):
    """A box given with corners reversed still crops (corners are sorted)."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink, bbox_source='path', bbox_path='payload.crop',
                 bbox_format='x1y1x2y2', bbox_space='normalized')
    out = _run(sink, node, {'image': _img(), 'crop': [0.6, 0.7, 0.1, 0.2]})
    assert out['bbox'] == [64, 96, 384, 336]


def test_path_missing_reports_and_no_send(node_classes):
    errs = []
    sink = node_classes['sink'](name='sink')
    node = _make(sink, bbox_source='path', bbox_path='payload.nope',
                 bbox_format='x1y1x2y2', bbox_space='normalized')
    node.report_error = lambda m: errs.append(m)
    node.on_input({'payload': {'image': _img(), 'crop': [0.1, 0.2, 0.6, 0.7]}})
    assert sink.received == []
    assert errs


def test_path_bad_length_reports(node_classes):
    errs = []
    sink = node_classes['sink'](name='sink')
    node = _make(sink, bbox_source='path', bbox_path='payload.crop',
                 bbox_format='x1y1x2y2', bbox_space='normalized')
    node.report_error = lambda m: errs.append(m)
    node.on_input({'payload': {'image': _img(), 'crop': [0.1, 0.2]}})  # only 2
    assert sink.received == []
    assert errs


# --- regressions: numpy-image output, detections, manual ---

def test_numpy_image_output(node_classes):
    """A raw numpy image must crop cleanly (guards the 'if encoded is not
    None' fix - plain truthiness raises on an ndarray)."""
    sink = node_classes['sink'](name='sink')
    node = _make(sink, bbox_source='path', bbox_path='payload.crop',
                 bbox_format='x1y1x2y2', bbox_space='normalized')
    out = _run(sink, node, {'image': _img(), 'crop': [0.0, 0.0, 0.5, 0.5]})
    assert isinstance(out['image'], np.ndarray)
    assert out['image'].shape == (240, 320, 3)


def test_detections_mode_still_works(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, bbox_source='detections', output_mode='separate')
    out = _run(sink, node, {'image': _img(), 'detections': [{'bbox': [0.1, 0.2, 0.6, 0.7]}]})
    assert out['bbox'] == [64, 96, 384, 336]


def test_manual_mode_still_works(node_classes):
    sink = node_classes['sink'](name='sink')
    node = _make(sink, bbox_source='manual', x1=0.0, y1=0.0, x2=0.5, y2=0.5)
    out = _run(sink, node, {'image': _img()})
    assert out['bbox'] == [0, 0, 320, 240]
