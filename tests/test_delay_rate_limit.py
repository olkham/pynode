"""Rate-limiter timing tests for DelayNode (rate mode) and RateProbeNode math.

These tests are fully deterministic and thread-free:

* The rate limiter's drop path and the rate probe are synchronous, so nodes are
  driven directly via ``on_input`` with a fake monotonic clock injected into the
  node module (no real ``time`` and no ``time.sleep``).
* Queue mode's drainer normally uses ``threading.Timer``; here ``Timer`` is
  replaced with a fake scheduler that records callbacks and fires them
  deterministically, advancing the fake clock by each timer's delay. No real
  threads are ever started, so there is nothing to leak or join.

No Flask app, WorkflowManager, or workflows/ directory is touched.
"""

import random
import types

import pytest

from pynode.nodes.DelayNode import delay_node as delay_module
from pynode.nodes.DelayNode.delay_node import DelayNode
from pynode.nodes.RateProbeNode import rate_probe_node as probe_module
from pynode.nodes.RateProbeNode.rate_probe_node import RateProbeNode
from pynode.nodes.base_node import MessageKeys


# ----------------------------------------------------------------------
# Fake clock + fake timer scheduler
# ----------------------------------------------------------------------

class _Clock:
    """Controllable monotonic clock. ``t`` is advanced by the test."""

    def __init__(self, t=1000.0):
        self.t = float(t)

    def monotonic(self):
        return self.t


class _FakeTimer:
    """Stand-in for ``threading.Timer`` that never starts a thread."""

    def __init__(self, scheduler, delay, callback):
        self._scheduler = scheduler
        self.delay = float(delay)
        self.callback = callback
        self.daemon = False

    def start(self):
        self._scheduler.pending.append(self)

    def cancel(self):
        if self in self._scheduler.pending:
            self._scheduler.pending.remove(self)


class _Scheduler:
    """Deterministic replacement for ``threading.Timer`` scheduling.

    Firing a timer advances the fake clock by exactly the timer's delay, so a
    timer scheduled for ``next_allowed - now`` fires precisely at
    ``next_allowed`` - i.e. on-schedule with zero latency. That lets a test
    assert the drainer has no drift.
    """

    def __init__(self, clock):
        self.clock = clock
        self.pending = []

    def timer_factory(self, delay, callback, *args, **kwargs):
        return _FakeTimer(self, delay, callback)

    def drain(self, max_steps=100):
        steps = 0
        while self.pending and steps < max_steps:
            timer = self.pending.pop(0)
            self.clock.t += timer.delay
            timer.callback()
            steps += 1
        assert not self.pending, "timers still pending after drain (possible loop)"


@pytest.fixture
def clock(monkeypatch):
    """Inject a fake monotonic clock into the DelayNode module."""
    c = _Clock()
    fake_time = types.SimpleNamespace(monotonic=c.monotonic, time=lambda: c.t,
                                      sleep=lambda _s: None)
    monkeypatch.setattr(delay_module, 'time', fake_time)
    return c


@pytest.fixture
def probe_clock(monkeypatch):
    """Inject a fake monotonic clock into the RateProbeNode module."""
    c = _Clock()
    fake_time = types.SimpleNamespace(monotonic=c.monotonic, time=lambda: c.t)
    monkeypatch.setattr(probe_module, 'time', fake_time)
    return c


# ----------------------------------------------------------------------
# DelayNode - rate limit / drop mode
# ----------------------------------------------------------------------

def _make_rate_node(rate_drop='drop', rate=1, rate_time=1):
    node = DelayNode(name='delay')
    node.configure({
        'mode': 'rate',
        'rate': rate,
        'rate_time': rate_time,
        'rate_drop': rate_drop,
        MessageKeys.DROP_MESSAGES: False,
    })
    return node


def _drive_drop(clock, arrivals, rate=1, rate_time=1):
    """Feed arrivals (absolute clock times) into a drop-mode node.

    Returns the list of clock times at which a message was passed through.
    """
    node = _make_rate_node('drop', rate, rate_time)
    passed = []
    node.send = lambda msg, output_index=0: passed.append(clock.t)
    for t in arrivals:
        clock.t = t
        node.on_input(node.create_message(payload=t))
    return passed


class TestDropModeTiming:

    def test_steady_input_yields_steady_output(self, clock):
        # Arrivals every 0.5s, rate limit of 1 per 1.0s -> pass every other one.
        base = 1000.0
        arrivals = [base + 0.5 * k for k in range(40)]
        passed = _drive_drop(clock, arrivals)

        gaps = [b - a for a, b in zip(passed, passed[1:])]
        assert len(passed) == 20                      # exactly one per interval
        assert gaps, "expected multiple passed messages"
        # Zero drift: every gap is exactly one interval.
        assert all(abs(g - 1.0) < 1e-9 for g in gaps), gaps

    def test_tolerates_arrival_jitter(self, clock):
        # +/-20ms scheduling jitter must NOT halve throughput (the reported bug).
        rng = random.Random(12345)
        base = 1000.0
        arrivals = [base + 0.5 * k + rng.uniform(-0.02, 0.02) for k in range(40)]
        passed = _drive_drop(clock, arrivals)

        gaps = [b - a for a, b in zip(passed, passed[1:])]
        assert 19 <= len(passed) <= 21                # still ~one per interval
        # Steady 1 per interval within 5% despite jitter.
        assert all(0.95 <= g <= 1.05 for g in gaps), gaps
        mean = sum(gaps) / len(gaps)
        assert abs(mean - 1.0) < 0.01

    def test_no_burst_after_idle_gap(self, clock):
        node = _make_rate_node('drop')
        passed = []
        node.send = lambda msg, output_index=0: passed.append(clock.t)

        clock.t = 1000.0
        node.on_input(node.create_message(payload='first'))

        # Long idle, then a rapid backlog of arrivals.
        for t in (1010.0, 1010.2, 1010.4, 1010.6, 1010.8, 1011.0):
            clock.t = t
            node.on_input(node.create_message(payload=t))

        # After the idle gap exactly ONE message passes immediately (1010.0),
        # then it resumes one-per-interval (next at 1011.0) - not a burst that
        # flushes the whole backlog.
        assert passed == [1000.0, 1010.0, 1011.0]

    def test_first_message_passes_immediately(self, clock):
        node = _make_rate_node('drop')
        passed = []
        node.send = lambda msg, output_index=0: passed.append(clock.t)
        clock.t = 5000.0
        node.on_input(node.create_message(payload='x'))
        assert passed == [5000.0]

    def test_faster_rate_configuration(self, clock):
        # rate=2 per 1s => interval 0.5s. Arrivals every 0.25s => pass every other.
        base = 1000.0
        arrivals = [base + 0.25 * k for k in range(20)]
        passed = _drive_drop(clock, arrivals, rate=2, rate_time=1)
        gaps = [b - a for a, b in zip(passed, passed[1:])]
        assert all(abs(g - 0.5) < 1e-9 for g in gaps), gaps


class TestQueueModeTiming:

    def test_queue_drains_in_order_at_steady_interval(self, clock, monkeypatch):
        scheduler = _Scheduler(clock)
        monkeypatch.setattr(delay_module.threading, 'Timer',
                            scheduler.timer_factory)

        node = _make_rate_node('queue')
        passed = []
        node.send = lambda msg, output_index=0: passed.append(
            (clock.t, msg['payload']))

        # Five messages arrive simultaneously; one passes, four are queued.
        clock.t = 1000.0
        for i in range(5):
            node.on_input(node.create_message(payload=i))

        scheduler.drain()

        times = [t for t, _ in passed]
        payloads = [p for _, p in passed]
        assert payloads == [0, 1, 2, 3, 4]                       # order kept
        assert times == [1000.0, 1001.0, 1002.0, 1003.0, 1004.0]  # steady, no drift
        assert node.processing_queue is False
        assert node.queued_messages == []


# ----------------------------------------------------------------------
# RateProbeNode - rate math
# ----------------------------------------------------------------------

def _make_probe(window_size):
    node = RateProbeNode(name='probe')
    node.configure({'window_size': window_size})
    return node


def _feed_probe(node, clock, times):
    for i, t in enumerate(times):
        clock.t = t
        node.on_input({'payload': i, 'topic': 't'})


class TestRateProbeMath:

    def test_full_window_steady_rate(self, probe_clock):
        node = _make_probe(5.0)
        _feed_probe(node, probe_clock, [1000.0 + k for k in range(11)])  # 1/s
        assert abs(node.get_rate() - 1.0) < 1e-9
        assert node.get_rate_display() == '1/s'

    def test_partial_window_not_overstated(self, probe_clock):
        # Only 3 messages (1s apart) in a 5s window. The old count/window math
        # gave 3/5 = 0.6/s => "1.7s/msg" (overstated). Interval math is exact.
        node = _make_probe(5.0)
        _feed_probe(node, probe_clock, [1000.0, 1001.0, 1002.0])
        assert abs(node.get_rate() - 1.0) < 1e-9
        assert node.get_rate_display() == '1/s'

    def test_slow_stream_seconds_per_message(self, probe_clock):
        # 0.5 msg/s -> display in seconds per message.
        node = _make_probe(10.0)
        _feed_probe(node, probe_clock, [1000.0 + 2.0 * k for k in range(6)])
        assert abs(node.get_rate() - 0.5) < 1e-9
        assert node.get_rate_display() == '2s/msg'

    def test_immune_to_boundary_jitter(self, probe_clock):
        # As the oldest timestamp ages in/out of the window the count changes by
        # +/-1, but so does the span, so the interval-based rate stays put.
        # (count/window would flip between 1.2/s and 1.0/s here.)
        node = _make_probe(5.0)
        _feed_probe(node, probe_clock, [1000.0 + k for k in range(6)])  # ts 1000..1005
        probe_clock.t = 1005.0
        r1 = node.get_rate()
        probe_clock.t = 1005.001   # oldest (1000) now ages out
        r2 = node.get_rate()
        assert abs(r1 - 1.0) < 1e-9
        assert abs(r2 - 1.0) < 1e-9
        assert node.get_rate_display() == '1/s'

    def test_single_message_has_zero_rate(self, probe_clock):
        node = _make_probe(5.0)
        _feed_probe(node, probe_clock, [1000.0])
        assert node.get_rate() == 0.0
        assert node.get_rate_display() == '0/s'

    def test_message_passes_through_with_stats(self, probe_clock):
        node = _make_probe(5.0)
        captured = []
        node.send = lambda msg, output_index=0: captured.append(msg)
        probe_clock.t = 1000.0
        node.on_input({'payload': 'x', 'topic': 't'})
        probe_clock.t = 1001.0
        node.on_input({'payload': 'y', 'topic': 't'})

        assert len(captured) == 2
        stats = captured[-1][MessageKeys.PAYLOAD]
        assert {'rate', 'display', 'window_size', 'message_count'} <= set(stats)
        assert stats['message_count'] == 2
        assert abs(stats['rate'] - 1.0) < 1e-9
