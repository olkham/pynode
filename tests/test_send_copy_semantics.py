"""Copy semantics of ``BaseNode.send()`` (the message-passing hot path).

``send()`` has a single-recipient fast path: when exactly one recipient will
actually receive a call, it gets a *shallow* copy (a fresh top-level dict that
shares payload/nested objects with the sender's msg). Any fan-out (>1 actual
recipient) deep-copies for every recipient so branches never alias.

These tests exercise ``send()`` synchronously: it only queues (or delivers to a
direct sink) - so recipients' messages are read straight off ``_message_queue``
with ``get_nowait()`` or off a recording sink, and NO worker threads are ever
started. Nodes are built directly; nothing touches the real data dir, the
module-level app, or workflows/.
"""

import numpy as np

from pynode.nodes.base_node import BaseNode, MessageKeys


class _DirectSink(BaseNode):
    """Sink (no outputs) with on_input_direct: send() delivers synchronously."""

    input_count = 1
    output_count = 0

    def __init__(self, node_id=None, name=""):
        super().__init__(node_id=node_id, name=name)
        self.received = []

    def on_input_direct(self, msg, input_index=0):
        self.received.append(msg)


def _drain(target):
    """Pop the single queued (msg, input_index) from a target, non-blocking."""
    msg, input_index = target._message_queue.get_nowait()
    assert target._message_queue.empty()
    return msg, input_index


# ------------------------------------------------------------------
# Queued path
# ------------------------------------------------------------------

class TestQueuedFastPath:

    def test_single_recipient_shares_payload_but_not_top_level(self):
        src = BaseNode(name='src')
        target = BaseNode(name='target')
        src.connect(target, 0, 0)

        payload = {'k': {'v': 1}}
        msg = src.create_message(payload=payload)
        src.send(msg)

        out, idx = _drain(target)
        assert idx == 0
        # Fast path: payload (and its nested objects) are shared by reference.
        assert out[MessageKeys.PAYLOAD] is payload
        # ...but the top-level dict is a fresh one, so the sender's msg is not
        # polluted with emit metadata.
        assert out is not msg
        assert MessageKeys.TIMESTAMP_EMIT not in msg
        assert MessageKeys.AGE not in msg

    def test_single_recipient_shares_numpy_frame(self):
        src = BaseNode(name='src')
        target = BaseNode(name='target')
        src.connect(target, 0, 0)

        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        msg = src.create_message(payload={MessageKeys.IMAGE.PATH: frame})
        src.send(msg)

        out, _ = _drain(target)
        # The whole point of the fast path: the frame is NOT copied.
        assert out[MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH] is frame

    def test_metadata_stamped_on_queued_path(self):
        src = BaseNode(name='src')
        target = BaseNode(name='target')
        src.connect(target, 0, 0)
        src.drop_count = 3

        src.send(src.create_message(payload='x'))

        out, _ = _drain(target)
        for key in (MessageKeys.TIMESTAMP_EMIT, MessageKeys.AGE,
                    MessageKeys.DROP_COUNT, MessageKeys.QUEUE_LENGTH):
            assert key in out
        assert out[MessageKeys.DROP_COUNT] == 3
        assert out[MessageKeys.AGE] >= 0


class TestQueuedFanOut:

    def test_two_recipients_get_distinct_deep_copies(self):
        src = BaseNode(name='src')
        t1 = BaseNode(name='t1')
        t2 = BaseNode(name='t2')
        src.connect(t1, 0, 0)
        src.connect(t2, 0, 0)

        payload = {'k': {'v': 1}}
        msg = src.create_message(payload=payload)
        src.send(msg)

        out1, _ = _drain(t1)
        out2, _ = _drain(t2)
        # Fan-out (>1) deep-copies: no aliasing with the sender or each other.
        assert out1[MessageKeys.PAYLOAD] is not payload
        assert out2[MessageKeys.PAYLOAD] is not payload
        assert out1[MessageKeys.PAYLOAD] is not out2[MessageKeys.PAYLOAD]
        assert out1[MessageKeys.PAYLOAD] == {'k': {'v': 1}}

        # Mutating one recipient's copy affects neither sibling nor source.
        out1[MessageKeys.PAYLOAD]['k']['v'] = 999
        assert out2[MessageKeys.PAYLOAD] == {'k': {'v': 1}}
        assert payload == {'k': {'v': 1}}


# ------------------------------------------------------------------
# Direct-sink path (output_count == 0 with on_input_direct)
# ------------------------------------------------------------------

class TestDirectSinkPath:

    def test_single_sink_shares_payload(self):
        src = BaseNode(name='src')
        sink = _DirectSink(name='sink')
        src.connect(sink, 0, 0)

        payload = {'k': 1}
        msg = src.create_message(payload=payload)
        src.send(msg)

        assert len(sink.received) == 1  # delivered synchronously, no threads
        out = sink.received[0]
        assert out[MessageKeys.PAYLOAD] is payload   # shared
        assert out is not msg                        # fresh top-level dict
        # Direct-sink path stamps emit/age/queue_length (drop_count is the
        # queued path's field only - preserved exactly as before).
        assert MessageKeys.TIMESTAMP_EMIT in out
        assert MessageKeys.AGE in out
        assert MessageKeys.QUEUE_LENGTH in out
        assert MessageKeys.DROP_COUNT not in out

    def test_two_sinks_get_distinct_deep_copies(self):
        src = BaseNode(name='src')
        s1 = _DirectSink(name='s1')
        s2 = _DirectSink(name='s2')
        src.connect(s1, 0, 0)
        src.connect(s2, 0, 0)

        payload = {'k': 1}
        src.send(src.create_message(payload=payload))

        out1 = s1.received[0]
        out2 = s2.received[0]
        assert out1[MessageKeys.PAYLOAD] is not payload
        assert out2[MessageKeys.PAYLOAD] is not payload
        assert out1[MessageKeys.PAYLOAD] is not out2[MessageKeys.PAYLOAD]


# ------------------------------------------------------------------
# Recipient counting: disabled / dropped targets don't count
# ------------------------------------------------------------------

class TestRecipientCounting:

    def test_disabled_target_skipped_and_leaves_one_fast_path(self):
        src = BaseNode(name='src')
        live = BaseNode(name='live')
        dead = BaseNode(name='dead')
        src.connect(live, 0, 0)
        src.connect(dead, 0, 0)
        dead.enabled = False

        payload = {'k': 1}
        src.send(src.create_message(payload=payload))

        # Disabled target got nothing and was not counted as a drop.
        assert dead._message_queue.empty()
        assert dead.drop_count == 0
        # Only ONE effective recipient -> fast path -> payload shared.
        out, _ = _drain(live)
        assert out[MessageKeys.PAYLOAD] is payload

    def test_busy_target_parks_the_original_and_copies_on_pickup(self):
        """A busy target holds the sender's objects uncopied; the live one
        gets its own copy now. The busy target's copy is deferred to pickup."""
        src = BaseNode(name='src')
        live = BaseNode(name='live')
        busy = BaseNode(name='busy')
        src.connect(live, 0, 0)
        src.connect(busy, 0, 0)
        busy._processing = True  # drop_while_busy defaults True -> parked

        payload = {'k': 1}
        src.send(src.create_message(payload=payload))

        # Nothing queued, nothing dropped: the message waits in the inbox.
        assert busy._message_queue.empty() and busy.drop_count == 0
        parked, input_index, lazy_deep = busy._pending[0]
        assert parked[MessageKeys.PAYLOAD] is payload     # no copy made by the sender
        assert lazy_deep is True                          # copy happens on pickup
        # The other branch is isolated from it.
        out, _ = _drain(live)
        assert out[MessageKeys.PAYLOAD] is not payload
        assert out[MessageKeys.PAYLOAD] == payload

    def test_sole_busy_target_is_never_copied(self):
        """The common chain (camera -> detector): no deepcopy at all."""
        src, busy = BaseNode(name='src'), BaseNode(name='busy')
        src.connect(busy, 0, 0)
        busy._processing = True

        payload = {'k': 1}
        src.send(src.create_message(payload=payload))

        parked, _, lazy_deep = busy._pending[0]
        assert parked[MessageKeys.PAYLOAD] is payload and lazy_deep is False

    def test_lazy_copy_isolates_the_busy_branch(self):
        """End to end: the busy node mutates its message; the sibling branch
        that shares the original must not see it."""
        import threading
        import time

        release, started = threading.Event(), threading.Event()
        got = []

        class _Mutator(BaseNode):
            def on_input(self, msg, input_index=0):
                started.set()
                if not release.is_set():
                    release.wait(5)
                msg[MessageKeys.PAYLOAD]['frame'][:] = 255
                got.append(msg[MessageKeys.PAYLOAD]['frame'])

        class _Reader(BaseNode):
            shares_input = True

        src, mutator, reader = BaseNode(name='src'), _Mutator(name='m'), _Reader(name='r')
        src.connect(mutator)
        src.connect(reader)
        mutator.on_start()
        try:
            src.send(src.create_message(payload={'frame': np.zeros(4, dtype=np.uint8)}))
            assert started.wait(5)
            frame = np.zeros(4, dtype=np.uint8)
            src.send(src.create_message(payload={'frame': frame}))   # parked while busy
            release.set()
            deadline = time.time() + 5
            while len(got) < 2 and time.time() < deadline:
                time.sleep(0.01)
        finally:
            release.set()
            mutator.on_stop()

        assert len(got) == 2 and got[1].tolist() == [255] * 4
        assert frame.tolist() == [0] * 4          # the shared original is untouched
        # The read-only node was handed the original, uncopied (its second
        # message is parked: its worker is not running in this test).
        shared, _, lazy_deep = reader._pending[0]
        assert shared[MessageKeys.PAYLOAD]['frame'] is frame
        assert lazy_deep is False

    def test_two_live_plus_one_dropped_still_deep_copies_the_two(self):
        src = BaseNode(name='src')
        t1 = BaseNode(name='t1')
        t2 = BaseNode(name='t2')
        busy = BaseNode(name='busy')
        src.connect(t1, 0, 0)
        src.connect(t2, 0, 0)
        src.connect(busy, 0, 0)
        busy._processing = True

        payload = {'k': 1}
        src.send(src.create_message(payload=payload))

        assert busy._message_queue.empty() and busy.drop_count == 0
        assert busy._pending[0][0][MessageKeys.PAYLOAD] is payload
        out1, _ = _drain(t1)
        out2, _ = _drain(t2)
        # Two real recipients -> both isolated from the source and each other.
        assert out1[MessageKeys.PAYLOAD] is not payload
        assert out2[MessageKeys.PAYLOAD] is not payload
        assert out1[MessageKeys.PAYLOAD] is not out2[MessageKeys.PAYLOAD]
