"""Tests for the Link node family (LinkOutNode / LinkInNode) and the LinkBus.

These exercise cross-workflow message passing: two independent WorkflowEngine
instances in one process, a LinkOut in engine A publishing on a channel and a
LinkIn in engine B (feeding a recording sink) receiving on the same channel.

Safety: every engine started here is stopped in a try/finally so no worker
threads or bus registrations leak between tests. Channel names are unique per
test to avoid any cross-test contamination of the process-wide bus.
"""

import pytest

from pynode.workflow_engine import WorkflowEngine
from pynode.nodes.LinkNode.link_out_node import LinkOutNode
from pynode.nodes.LinkNode.link_in_node import LinkInNode
from pynode.nodes.LinkNode.link_bus import link_bus


def _make_engine(sink_cls):
    """A bare engine with the Link nodes and the recording sink registered."""
    eng = WorkflowEngine()
    eng.register_node_type(LinkOutNode)
    eng.register_node_type(LinkInNode)
    eng.register_node_type(sink_cls)
    return eng


def _build_sink_chain(engine, channel, sink_cls):
    """Create LinkIn -> sink in ``engine`` and return (link_in, sink)."""
    link_in = engine.create_node('LinkInNode', config={'channel': channel})
    sink = engine.create_node(sink_cls.__name__)
    engine.connect_nodes(link_in.id, sink.id)
    return link_in, sink


def test_cross_engine_delivery(node_classes):
    """A LinkOut in engine A delivers to a LinkIn (-> sink) in engine B."""
    sink_cls = node_classes['sink']
    channel = 'chan-cross'

    engine_a = _make_engine(sink_cls)
    engine_b = _make_engine(sink_cls)
    link_out = engine_a.create_node('LinkOutNode', config={'channel': channel})
    link_in, sink = _build_sink_chain(engine_b, channel, sink_cls)

    try:
        engine_a.start()
        engine_b.start()

        # LinkIn should have registered on the bus when engine B started.
        assert link_bus.subscriber_count(channel) == 1

        msg = link_out.create_message(payload='hello', topic='t')
        link_out.on_input(msg)  # inject directly -> publishes to the bus

        assert len(sink.received) == 1
        assert sink.received[0].get('payload') == 'hello'
    finally:
        engine_a.stop()
        engine_b.stop()

    # Both engines stopped -> no lingering subscribers.
    assert link_bus.subscriber_count(channel) == 0


def test_unregister_on_stop(node_classes):
    """After engine B stops, publishing does not deliver and does not error."""
    sink_cls = node_classes['sink']
    channel = 'chan-unreg'

    engine_a = _make_engine(sink_cls)
    engine_b = _make_engine(sink_cls)
    link_out = engine_a.create_node('LinkOutNode', config={'channel': channel})
    link_in, sink = _build_sink_chain(engine_b, channel, sink_cls)

    try:
        engine_a.start()
        engine_b.start()
        assert link_bus.subscriber_count(channel) == 1

        # Stop the receiving engine: LinkIn.on_stop must unregister.
        engine_b.stop()
        assert link_bus.subscriber_count(channel) == 0

        # Publishing now must be a harmless no-op (no delivery, no error).
        msg = link_out.create_message(payload='after-stop')
        link_out.on_input(msg)
        assert sink.received == []
    finally:
        engine_a.stop()
        # engine_b already stopped; stop() is idempotent.
        engine_b.stop()


def test_no_delivery_to_disabled_link_in(node_classes):
    """A disabled LinkIn does not receive, even while registered."""
    sink_cls = node_classes['sink']
    channel = 'chan-disabled'

    engine_a = _make_engine(sink_cls)
    engine_b = _make_engine(sink_cls)
    link_out = engine_a.create_node('LinkOutNode', config={'channel': channel})
    link_in, sink = _build_sink_chain(engine_b, channel, sink_cls)

    try:
        engine_a.start()
        engine_b.start()

        link_in.enabled = False

        msg = link_out.create_message(payload='blocked')
        link_out.on_input(msg)

        assert sink.received == []
    finally:
        engine_a.stop()
        engine_b.stop()


def test_no_delivery_before_engine_started(node_classes):
    """A LinkIn only registers on start, so an unstarted engine never receives."""
    sink_cls = node_classes['sink']
    channel = 'chan-unstarted'

    engine_a = _make_engine(sink_cls)
    engine_b = _make_engine(sink_cls)
    link_out = engine_a.create_node('LinkOutNode', config={'channel': channel})
    link_in, sink = _build_sink_chain(engine_b, channel, sink_cls)

    try:
        engine_a.start()
        # engine_b intentionally NOT started -> LinkIn never registered.
        assert link_bus.subscriber_count(channel) == 0

        msg = link_out.create_message(payload='nobody-home')
        link_out.on_input(msg)
        assert sink.received == []
    finally:
        engine_a.stop()
        engine_b.stop()


def test_same_engine_same_channel_delivery(node_classes):
    """LinkOut and LinkIn on one channel in the SAME engine still deliver."""
    sink_cls = node_classes['sink']
    channel = 'chan-same'

    engine = _make_engine(sink_cls)
    link_out = engine.create_node('LinkOutNode', config={'channel': channel})
    link_in, sink = _build_sink_chain(engine, channel, sink_cls)

    try:
        engine.start()
        msg = link_out.create_message(payload='local')
        link_out.on_input(msg)
        assert len(sink.received) == 1
        assert sink.received[0].get('payload') == 'local'
    finally:
        engine.stop()


def test_fan_out_to_multiple_link_ins(node_classes):
    """Two LinkIn nodes (in different engines) on one channel both receive."""
    sink_cls = node_classes['sink']
    channel = 'chan-fanout'

    engine_a = _make_engine(sink_cls)
    engine_b = _make_engine(sink_cls)
    engine_c = _make_engine(sink_cls)
    link_out = engine_a.create_node('LinkOutNode', config={'channel': channel})
    _, sink_b = _build_sink_chain(engine_b, channel, sink_cls)
    _, sink_c = _build_sink_chain(engine_c, channel, sink_cls)

    try:
        engine_a.start()
        engine_b.start()
        engine_c.start()
        assert link_bus.subscriber_count(channel) == 2

        link_out.on_input(link_out.create_message(payload='broadcast'))

        assert len(sink_b.received) == 1
        assert len(sink_c.received) == 1
        # Deep-copy isolation: each sink got its own object.
        assert sink_b.received[0] is not sink_c.received[0]
    finally:
        engine_a.stop()
        engine_b.stop()
        engine_c.stop()


def test_empty_channel_is_inactive(node_classes):
    """An empty channel does not register and publishing on it is a no-op."""
    sink_cls = node_classes['sink']

    engine = _make_engine(sink_cls)
    link_out = engine.create_node('LinkOutNode', config={'channel': ''})
    link_in, sink = _build_sink_chain(engine, '', sink_cls)

    try:
        engine.start()
        # Empty channel never registers.
        assert link_bus.subscriber_count('') == 0
        link_out.on_input(link_out.create_message(payload='x'))
        assert sink.received == []
    finally:
        engine.stop()
