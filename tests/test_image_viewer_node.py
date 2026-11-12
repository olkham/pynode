"""Tests for ImageViewerNode's lazy, display-sized encoding.

The viewer is a direct sink: its ``on_input`` runs on the SENDING node's
thread for every message. It used to JPEG-encode the full frame right there,
which cost a 60 fps 1080p source more than its whole frame budget. These tests
pin the fix: receiving is free, encoding happens once per displayed frame, at
display size, on whoever asks for it.

Nodes are driven directly - no Flask app, no workflows dir, no threads.
"""

import base64

import cv2
import numpy as np
import pytest

from pynode.nodes.base_node import BaseNode
from pynode.nodes.ImageViewerNode.image_viewer_node import ImageViewerNode
from pynode.nodes.RateProbeNode.rate_probe_node import RateProbeNode


def _frame(width=1920, height=1080, seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (height, width, 3), dtype=np.uint8)


def _viewer(**config):
    node = ImageViewerNode(name='viewer')
    if config:
        node.configure(config)
    return node


def _decode(encoded):
    data = np.frombuffer(base64.b64decode(encoded['data']), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


@pytest.fixture
def no_rate_cap(monkeypatch):
    monkeypatch.setattr(ImageViewerNode, 'UI_MAX_FPS', 1e9)


# --- receiving is free ---------------------------------------------------

def test_receiving_a_frame_does_not_encode(monkeypatch):
    node = _viewer()
    calls = []
    monkeypatch.setattr(cv2, 'imencode', lambda *a, **k: calls.append(1) or (True, np.zeros(1, np.uint8)))
    frame = _frame()

    for _ in range(5):
        node.on_input_direct({'payload': {'image': frame}})

    assert calls == []
    assert node.current_frame is frame          # a reference, not a copy


def test_viewer_and_rate_probe_share_input():
    assert ImageViewerNode.shares_input is True
    assert RateProbeNode.shares_input is True
    assert BaseNode.shares_input is False        # opt-in only


def test_fan_out_does_not_copy_the_frame_for_the_viewer():
    """Video -> (viewer, processing node): only the processing branch copies."""
    src, viewer, worker = BaseNode(name='src'), _viewer(), BaseNode(name='worker')
    src.connect(viewer)
    src.connect(worker)
    frame = _frame(64, 48)

    src.send(src.create_message(payload={'image': frame}))

    assert viewer.current_frame is frame
    queued, _ = worker._message_queue.get_nowait()
    assert queued['payload']['image'] is not frame
    assert np.array_equal(queued['payload']['image'], frame)


# --- encoding ------------------------------------------------------------

def test_preview_is_downscaled_to_the_display_size(no_rate_cap):
    node = _viewer(width=320, height=240)
    node.on_input({'payload': {'image': _frame(1920, 1080)}})

    encoded = node.get_current_frame_sse()['data']

    # Fits inside 2x the card (640x480), aspect ratio preserved.
    assert (encoded['width'], encoded['height']) == (640, 360)
    assert _decode(encoded).shape[:2] == (360, 640)
    assert encoded['format'] == 'jpeg' and encoded['encoding'] == 'base64'


def test_a_larger_card_gets_a_larger_preview(no_rate_cap):
    node = _viewer(width=800, height=450)
    node.on_input({'payload': {'image': _frame(1920, 1080)}})

    encoded = node.get_current_frame_sse()['data']

    assert (encoded['width'], encoded['height']) == (1600, 900)


def test_small_images_are_never_upscaled(no_rate_cap):
    node = _viewer()
    node.on_input({'payload': {'image': _frame(160, 120)}})

    encoded = node.get_current_frame_sse()['data']

    assert (encoded['width'], encoded['height']) == (160, 120)


def test_mjpeg_stream_stays_full_resolution():
    node = _viewer(width=320, height=240)
    node.on_input({'payload': {'image': _frame(1920, 1080)}})

    jpeg = next(node.get_mjpeg_stream())

    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[:2] == (1080, 1920)


def test_each_frame_is_encoded_once_however_many_consumers(monkeypatch, no_rate_cap):
    node = _viewer()
    real, calls = cv2.imencode, []

    def _counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(cv2, 'imencode', _counting)
    node.on_input({'payload': {'image': _frame(640, 480)}})

    sse = node.get_current_frame_sse()
    polled = node.get_current_frame()

    assert len(calls) == 1                       # second consumer hit the cache
    assert sse['data'] is polled

    node.on_input({'payload': {'image': _frame(640, 480, seed=1)}})
    node.get_current_frame_sse()
    assert len(calls) == 2
    assert len(node._encode_cache) == 1          # old frame's result was dropped


def test_already_encoded_input_is_accepted(no_rate_cap):
    ok, buffer = cv2.imencode('.jpg', _frame(320, 240))
    assert ok
    payload_image = {'format': 'jpeg', 'encoding': 'base64',
                     'data': base64.b64encode(buffer.tobytes()).decode('ascii')}
    node = _viewer()

    node.on_input({'payload': {'image': payload_image}})
    encoded = node.get_current_frame_sse()['data']

    assert _decode(encoded).shape[:2] == (240, 320)


# --- delivery bookkeeping ------------------------------------------------

def test_sse_and_polled_routes_dedupe_independently(no_rate_cap):
    node = _viewer()
    node.on_input({'payload': {'image': _frame(64, 48)}})

    assert node.get_current_frame_sse() is not None
    assert node.get_current_frame_sse() is None      # same frame, already sent
    assert node.get_current_frame() is not None      # the polled route still gets it
    assert node.get_current_frame() is None


def test_sse_frames_are_rate_capped(monkeypatch):
    import sys

    mod = sys.modules[ImageViewerNode.__module__]
    clock = [100.0]
    monkeypatch.setattr(mod.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(ImageViewerNode, 'UI_MAX_FPS', 30.0)
    node = _viewer()
    sent = 0

    # A 120 fps source for one second, polled every ~8 ms.
    for i in range(120):
        node.on_input({'payload': {'image': _frame(32, 24, seed=i)}})
        if node.get_current_frame_sse() is not None:
            sent += 1
        clock[0] += 1 / 120

    assert 28 <= sent <= 31


def test_nothing_to_show_before_the_first_frame():
    node = _viewer()

    assert node.get_current_frame() is None
    assert node.get_current_frame_sse() is None


def test_missing_image_path_reports_an_error(monkeypatch):
    node = _viewer()
    errors = []
    monkeypatch.setattr(node, 'report_error', lambda m: errors.append(m))

    node.on_input({'payload': {'not_image': 1}})

    assert node.current_frame is None
    assert errors and 'No data found' in errors[0]


def test_undecodable_data_reports_an_error_when_displayed(monkeypatch, no_rate_cap):
    node = _viewer()
    errors = []
    monkeypatch.setattr(node, 'report_error', lambda m: errors.append(m))

    node.on_input({'payload': {'image': 12345}})

    assert node.get_current_frame_sse() is None
    assert errors
