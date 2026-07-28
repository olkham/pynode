"""FramePacer behaviour, and the capture loops that depend on it.

The point of the pacer is throughput under *variable* per-iteration work:
the naive `sleep(interval - elapsed)` form discards the overshoot of every
slow iteration, so the achieved period becomes mean(max(interval, work))
instead of max(interval, mean(work)). These tests drive that case with a
stub whose work time alternates fast/slow, so no camera or codec is needed.
"""

import threading
import time

import numpy as np
import pytest

from pynode.nodes.base_node import MessageKeys
from pynode.nodes.pacing import FramePacer


class TestFramePacer:

    def test_holds_the_target_rate_for_uniform_work(self):
        pacer = FramePacer(0.01)
        start = time.perf_counter()
        for _ in range(20):
            assert pacer.wait() is True
        elapsed = time.perf_counter() - start
        assert 0.18 < elapsed < 0.30, elapsed

    def test_fast_iteration_repays_a_slow_one(self):
        """The whole point: the deadline is allowed to sit in the past, so the
        wait after an overrun is *shortened* by what the overrun consumed."""
        interval = 0.02
        pacer = FramePacer(interval)
        time.sleep(interval * 1.5)   # iteration overran by half an interval
        assert pacer.wait() is True  # already past the deadline -> immediate

        start = time.perf_counter()
        pacer.wait()
        # Repaying: this wait covers only the remaining half interval.
        assert time.perf_counter() - start < interval * 0.9

    def test_resyncs_instead_of_bursting_after_a_long_stall(self):
        interval = 0.01
        pacer = FramePacer(interval)
        time.sleep(interval * 30)  # a stall far beyond any repayment
        pacer.wait()
        # Deadline was resynced to now, so the next waits are full intervals
        # rather than 29 instant catch-up iterations.
        start = time.perf_counter()
        for _ in range(5):
            pacer.wait()
        assert time.perf_counter() - start > interval * 3

    def test_max_catchup_zero_disables_repayment(self):
        """Same overrun as above, but the deadline resyncs to now instead of
        being left in the past, so the next wait is a full interval."""
        interval = 0.02
        pacer = FramePacer(interval, max_catchup=0.0)
        time.sleep(interval * 1.5)
        pacer.wait()

        start = time.perf_counter()
        pacer.wait()
        assert time.perf_counter() - start > interval * 0.8

    def test_wait_returns_false_once_running_goes_false(self):
        running = True
        pacer = FramePacer(5.0, running=lambda: running, sleep_chunk=0.01)

        def stop_soon():
            time.sleep(0.05)
            nonlocal running
            running = False

        t = threading.Thread(target=stop_soon)
        t.start()
        try:
            start = time.perf_counter()
            assert pacer.wait() is False
            # Returned on the stop, not after the 5 s interval.
            assert time.perf_counter() - start < 1.0
        finally:
            t.join(timeout=2.0)

    def test_per_call_interval_overrides_the_default(self):
        pacer = FramePacer(10.0)
        start = time.perf_counter()
        pacer.wait(0.01)
        assert time.perf_counter() - start < 1.0

    def test_non_positive_interval_does_not_sleep(self):
        pacer = FramePacer(0.0)
        start = time.perf_counter()
        assert pacer.wait() is True
        assert time.perf_counter() - start < 0.01

    def test_reset_restarts_the_schedule(self):
        pacer = FramePacer(0.01)
        time.sleep(0.05)
        pacer.reset()
        start = time.perf_counter()
        pacer.wait()
        assert time.perf_counter() - start > 0.004


class _StubCamera:
    """Stands in for cv2.VideoCapture with a controllable read() cost.

    Alternates a fast and a slow read so the mean sits inside the frame
    budget while individual frames blow through it - the shape that exposed
    the pacing bug on real video.
    """

    def __init__(self, fast=0.002, slow=0.12, size=32):
        self.fast = fast
        self.slow = slow
        self._n = 0
        self._frame = np.zeros((size, size, 3), dtype=np.uint8)

    def isOpened(self):
        return True

    def read(self):
        time.sleep(self.slow if self._n % 4 == 3 else self.fast)
        self._n += 1
        return True, self._frame.copy()

    def release(self):
        pass


class TestCaptureLoopPacing:
    """CameraNode opens a device index, so the loop is driven directly with a
    stub camera instead - it only needs .isOpened()/.read()."""

    @pytest.fixture
    def camera_node(self, node_classes):
        from pynode.nodes.CameraNode.camera_node import CameraNode
        node = CameraNode(node_id='cam-pace', name='cam')
        sink = node_classes['sink'](node_id='cam-sink', name='sink')
        node.connect(sink)
        node.configure({MessageKeys.CAMERA.ENCODE_JPEG: False})
        try:
            yield node, sink
        finally:
            node.running = False
            node.camera = None

    def test_capture_loop_holds_target_rate_despite_slow_frames(self, camera_node):
        node, sink = camera_node
        # Mean read cost = (3*2 + 120)/4 = 31.5 ms, comfortably inside a 20 Hz
        # (50 ms) budget, but every 4th frame overruns it 2.4x. The spike has
        # to exceed the interval for this to discriminate at all - with a
        # spike of exactly one interval both pacings hit 20 fps.
        node.camera = _StubCamera(fast=0.002, slow=0.12)
        node.running = True

        thread = threading.Thread(target=node._capture_loop, args=(20,),
                                  daemon=True)
        thread.start()
        try:
            time.sleep(1.5)
        finally:
            node.running = False
            thread.join(timeout=3.0)
        assert not thread.is_alive()

        rate = len(sink.received) / 1.5
        # Measured: naive pacing 15.1 fps, FramePacer 19.3 against a 20 fps
        # target, so this threshold separates the two.
        assert rate > 18.0, f"only {rate:.1f} fps ({len(sink.received)} frames)"

    def test_capture_loop_stops_promptly(self, camera_node):
        node, sink = camera_node
        node.camera = _StubCamera(fast=0.001, slow=0.001)
        node.running = True
        thread = threading.Thread(target=node._capture_loop, args=(1,),
                                  daemon=True)
        thread.start()
        try:
            time.sleep(0.1)
            node.running = False
            start = time.perf_counter()
            thread.join(timeout=3.0)
            # Chunked sleep: stop is honoured well inside the 1 s interval.
            assert time.perf_counter() - start < 0.5
        finally:
            node.running = False
            thread.join(timeout=3.0)
        assert not thread.is_alive()
