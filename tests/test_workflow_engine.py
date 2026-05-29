"""Tests for the core WorkflowEngine behavior."""

import pytest

from pynode.workflow_engine import WorkflowEngine


def test_create_node_adds_to_engine(engine):
    node = engine.create_node('_SourceNode', name='src')
    assert node.id in engine.nodes
    assert engine.get_node(node.id) is node
    assert node.name == 'src'


def test_create_node_unknown_type_raises(engine):
    with pytest.raises(ValueError):
        engine.create_node('DoesNotExistNode')


def test_create_node_with_explicit_id(engine):
    node = engine.create_node('_SourceNode', node_id='fixed-id')
    assert node.id == 'fixed-id'
    assert engine.get_node('fixed-id') is node


def test_connect_nodes(engine):
    src = engine.create_node('_SourceNode')
    sink = engine.create_node('_SinkNode')
    engine.connect_nodes(src.id, sink.id)
    assert any(
        target.id == sink.id
        for targets in src.outputs.values()
        for target, _ in targets
    )


def test_connect_unknown_node_raises(engine):
    src = engine.create_node('_SourceNode')
    with pytest.raises(ValueError):
        engine.connect_nodes(src.id, 'missing')


def test_delete_node_removes_connections(engine):
    src = engine.create_node('_SourceNode')
    sink = engine.create_node('_SinkNode')
    engine.connect_nodes(src.id, sink.id)

    engine.delete_node(sink.id)

    assert sink.id not in engine.nodes
    # Source should no longer reference the deleted node
    assert all(
        target.id != sink.id
        for targets in src.outputs.values()
        for target, _ in targets
    )


def test_start_and_stop_toggle_running(engine):
    engine.create_node('_SourceNode')
    assert engine.running is False

    engine.start()
    assert engine.running is True

    engine.stop()
    assert engine.running is False


def test_start_is_idempotent(engine):
    engine.create_node('_SourceNode')
    engine.start()
    # A second start should not raise and should keep running.
    engine.start()
    assert engine.running is True
    engine.stop()


def test_synchronous_message_delivery_to_sink(engine):
    src = engine.create_node('_SourceNode')
    sink = engine.create_node('_SinkNode')
    engine.connect_nodes(src.id, sink.id)

    msg = src.create_message(payload='hello', topic='greeting')
    src.send(msg)

    assert len(sink.received) == 1
    assert sink.received[0]['payload'] == 'hello'
    assert sink.received[0]['topic'] == 'greeting'


def test_register_node_type_records_class():
    engine = WorkflowEngine()
    from tests.conftest import _SinkNode

    engine.register_node_type(_SinkNode)
    assert '_SinkNode' in engine.node_types
    assert engine.node_types['_SinkNode'] is _SinkNode
