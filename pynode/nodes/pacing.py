"""Frame pacing for node loops that emit at a target rate.

Split out of ``base_node`` so any node with a capture/playback/repeat loop
can pace itself correctly; re-exported from ``pynode.nodes.base_node``.
"""

import time
from typing import Callable, Optional


class FramePacer:
    """Absolute-deadline pacer for loops that emit at a fixed rate.

    The naive pattern - which several node loops used - is::

        while running:
            start = time.time()
            do_work()
            time.sleep(max(0, interval - (time.time() - start)))

    That silently discards the overshoot of every slow iteration: after work
    that overruns ``interval``, the next iteration still waits a *full*
    interval instead of firing immediately. The achieved period becomes
    ``mean(max(interval, work))`` instead of ``max(interval, mean(work))``,
    so any **variance** in the work costs throughput even when the mean sits
    comfortably inside budget. Measured on a 1080p H.264 file whose decode
    averages 22 ms against a 33.4 ms budget but spikes to 119 ms, that gap
    alone dragged a 30 fps source down to 23.5 fps.

    Tracking an absolute deadline lets a fast iteration repay a slow one.
    ``max_catchup`` bounds that repayment (in intervals) so a genuine stall
    resyncs instead of emitting an unbounded catch-up burst - important for
    live sources, where the frames to "catch up" with do not exist yet.

    **The bound has to exceed the spikes you mean to absorb.** A spike of k
    intervals leaves the loop k-1 intervals late, so anything under that
    resyncs and throws the repayment away - i.e. it silently degrades to the
    naive behaviour. Measured on a loop whose work spikes to 2.4x the
    interval every 4th iteration: ``max_catchup=1`` held 15.2 fps against a
    20 fps target (no better than the naive form), ``max_catchup=2`` reached
    19.3. The default of 3 covers spikes up to ~4x the frame budget, which
    spans what real capture and decode loops produce, while still resyncing
    out of a multi-second hang.

    The cost of repayment is burstiness: the frames right after a spike fire
    back to back to recover the schedule. Where that matters, feed the loop
    from a prefetch queue (as VideoReaderNode does) so spikes are absorbed
    before the pacer ever sees them, and the pacer only trims residual jitter.

    Timing uses ``time.perf_counter`` (monotonic, sub-microsecond) rather
    than ``time.time``, whose reported resolution on Windows is ~15.6 ms.

    Typical use - call ``wait()`` at the end of each iteration::

        pacer = FramePacer(1.0 / fps, running=lambda: self.running)
        while self.running:
            emit_one_frame()
            if not pacer.wait():
                break   # stopped mid-wait
    """

    # Longest single sleep, so a stopped loop is noticed promptly even when
    # the interval is seconds long.
    DEFAULT_SLEEP_CHUNK = 0.05

    # Intervals of lateness that may be repaid before the schedule resyncs.
    # Must exceed (spike / interval) - 1 or the repayment is discarded and
    # the pacer degrades to the naive behaviour; see the class docstring.
    DEFAULT_MAX_CATCHUP = 3.0

    def __init__(self, interval: float,
                 running: Optional[Callable[[], bool]] = None,
                 sleep_chunk: float = DEFAULT_SLEEP_CHUNK,
                 max_catchup: float = DEFAULT_MAX_CATCHUP):
        """
        Args:
            interval: Target seconds between iterations. May be overridden
                per call via ``wait(interval)`` for loops whose rate is
                re-read from config each frame.
            running: Predicate polled while sleeping; ``wait`` returns early
                (False) once it goes false. Defaults to always-running.
            sleep_chunk: Longest single ``time.sleep`` while waiting.
            max_catchup: How many intervals of lateness may be repaid before
                the schedule resyncs to now. 0 disables catch-up entirely
                (every iteration waits a fresh full interval).
        """
        self.interval = interval
        self._running = running if running is not None else _always
        self._sleep_chunk = sleep_chunk
        self._max_catchup = max_catchup
        self._deadline = time.perf_counter()

    def reset(self):
        """Restart the schedule from now (call when resuming after a pause)."""
        self._deadline = time.perf_counter()

    def wait(self, interval: Optional[float] = None) -> bool:
        """Sleep until the next deadline.

        Returns:
            True once the deadline is reached; False if ``running`` went
            false while waiting (the caller should break out of its loop).
        """
        step = self.interval if interval is None else interval
        if step <= 0:
            return self._running()

        self._deadline += step
        now = time.perf_counter()
        if now - self._deadline > step * self._max_catchup:
            # Too far behind to repay (stall, or the machine simply cannot
            # keep up): resync rather than chase a deadline we'll never meet.
            self._deadline = now

        while self._running():
            remaining = self._deadline - time.perf_counter()
            if remaining <= 0:
                return True
            time.sleep(min(remaining, self._sleep_chunk))
        return False


def _always() -> bool:
    return True
