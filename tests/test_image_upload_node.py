"""Tests for ImageUploadNode, focused on the Repeat Send capability.

Safety
------
* No Flask app / WorkflowManager / ``workflows/`` dir is touched - the node is
  instantiated and driven directly, wired to the conftest ``sink`` node
  (synchronous ``on_input_direct`` delivery).
* Every node started with ``on_start()`` is stopped with ``on_stop()`` in a
  ``try/finally`` before the test returns, so the repeat thread never outlives
  the test.
"""

import time

import cv2
import numpy as np
import pytest

from pynode.nodes.ImageUploadNode.image_upload_node import ImageUploadNode


def _jpeg_bytes(w=16, h=12):
    """Encode a small deterministic BGR image to JPEG file bytes."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 1] = 128
    ok, buf = cv2.imencode('.jpg', img)
    assert ok
    return buf.tobytes()


def _wait_until(predicate, timeout=5.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _make_node(sink, **config):
    node = ImageUploadNode(name='image-upload')
    if config:
        node.configure(config)
    node.connect(sink)
    node.on_start()
    return node


def test_upload_sends_once_by_default(node_classes):
    """With Repeat Send off, an upload emits exactly one message."""
    sink = node_classes['sink'](name='sink')
    node = _make_node(sink)
    try:
        node.receive_image(_jpeg_bytes(), 'pic.jpg')
        assert _wait_until(lambda: len(sink.received) == 1)
        time.sleep(0.2)
        assert len(sink.received) == 1  # no repeats
        img = sink.received[0]['payload']['image']
        assert img['width'] == 16 and img['height'] == 12
        assert img['format'] == 'jpeg' and img['data']
        assert sink.received[0]['payload']['filename'] == 'pic.jpg'
    finally:
        node.on_stop()


def test_repeat_send_achieves_requested_rate(node_classes):
    """Repeat Send must actually hit close to the requested rate, and stop
    promptly on on_stop().

    Regression guard for the pacing bug where Event.wait()/time.time()
    (both ~15 ms granularity on Windows) dragged a requested 30 fps down to
    ~11 fps under load. We request 30 fps and require the measured rate to
    clear a floor (20 fps) that the old implementation could not - with
    enough slack below 30 to stay stable on a loaded CI runner.
    """
    sink = node_classes['sink'](name='sink')
    node = _make_node(sink, repeat_send=True, repeat_rate=30)
    try:
        window = 1.5
        node.receive_image(_jpeg_bytes(), 'pic.jpg')
        t0 = time.perf_counter()
        time.sleep(window)
        count = len(sink.received)
        node.on_stop()
        elapsed = time.perf_counter() - t0
        rate = count / elapsed
        assert rate >= 20, f"repeat rate {rate:.1f}/s too low (requested 30)"

        # No sends after the thread is joined.
        time.sleep(0.15)
        assert len(sink.received) == count
    finally:
        node.on_stop()


def test_repeat_rebuilds_fresh_payload_each_send(node_classes):
    """Each send must own its payload dict tree - a downstream mutation of one
    message must not corrupt later sends (send() ownership contract)."""
    sink = node_classes['sink'](name='sink')
    node = _make_node(sink, repeat_send=True, repeat_rate=50)
    try:
        node.receive_image(_jpeg_bytes(), 'pic.jpg')
        assert _wait_until(lambda: len(sink.received) >= 3)
        node.on_stop()
        msgs = sink.received[:3]
        # Distinct payload dicts and distinct nested image dicts.
        assert len({id(m['payload']) for m in msgs}) == len(msgs)
        assert len({id(m['payload']['image']) for m in msgs}) == len(msgs)
        # Mutating one payload does not affect the node's stored data.
        msgs[0]['payload']['image']['data'] = 'CORRUPTED'
        fresh = node._build_message()
        assert fresh['payload']['image']['data'] != 'CORRUPTED'
    finally:
        node.on_stop()


def test_second_upload_replaces_image_without_extra_thread(node_classes):
    """A second upload swaps the image the repeat loop sends, without spawning
    a second timer thread."""
    sink = node_classes['sink'](name='sink')
    node = _make_node(sink, repeat_send=True, repeat_rate=50)
    try:
        node.receive_image(_jpeg_bytes(16, 12), 'first.jpg')
        assert _wait_until(lambda: len(sink.received) >= 2)
        thread1 = node._repeat_thread

        node.receive_image(_jpeg_bytes(32, 24), 'second.jpg')
        assert node._repeat_thread is thread1  # same thread, no double-start
        assert _wait_until(
            lambda: any(m['payload']['filename'] == 'second.jpg'
                        for m in sink.received))
        latest = sink.received[-1]['payload']['image']
        assert latest['width'] == 32 and latest['height'] == 24
    finally:
        node.on_stop()


def test_repeat_disabled_does_not_repeat(node_classes):
    """repeat_send off (even with a rate set) sends only the immediate one."""
    sink = node_classes['sink'](name='sink')
    node = _make_node(sink, repeat_send=False, repeat_rate=50)
    try:
        node.receive_image(_jpeg_bytes(), 'pic.jpg')
        assert _wait_until(lambda: len(sink.received) == 1)
        time.sleep(0.2)
        assert len(sink.received) == 1
        assert node._repeat_thread is None
    finally:
        node.on_stop()


def test_zero_rate_does_not_repeat(node_classes):
    """repeat_send on but rate 0 must not start a busy loop or divide by zero."""
    sink = node_classes['sink'](name='sink')
    node = _make_node(sink, repeat_send=True, repeat_rate=0)
    try:
        node.receive_image(_jpeg_bytes(), 'pic.jpg')
        assert _wait_until(lambda: len(sink.received) == 1)
        time.sleep(0.2)
        assert len(sink.received) == 1
        assert node._repeat_thread is None
    finally:
        node.on_stop()


def test_bad_image_reports_error_and_sends_nothing(node_classes):
    """Undecodable upload bytes report an error and emit no message."""
    sink = node_classes['sink'](name='sink')
    node = _make_node(sink, repeat_send=True, repeat_rate=20)
    try:
        node.receive_image(b'not an image', 'bad.txt')
        time.sleep(0.2)
        assert sink.received == []
        assert node._repeat_thread is None
    finally:
        node.on_stop()
