"""Tests for node auto-discovery and registration."""

from pynode import nodes
from pynode.nodes.base_node import BaseNode
from pynode.workflow_engine import WorkflowEngine


def test_get_all_node_types_returns_classes():
    node_types = nodes.get_all_node_types()
    assert isinstance(node_types, list)
    assert len(node_types) > 0


def test_discovered_node_types_are_base_node_subclasses():
    for node_class in nodes.get_all_node_types():
        assert issubclass(node_class, BaseNode)
        assert node_class is not BaseNode


def test_discovered_node_names_end_with_node():
    for node_class in nodes.get_all_node_types():
        assert node_class.__name__.endswith('Node')


def test_no_duplicate_node_type_names():
    names = [c.__name__ for c in nodes.get_all_node_types()]
    assert len(names) == len(set(names))


def test_all_discovered_types_can_register():
    engine = WorkflowEngine()
    for node_class in nodes.get_all_node_types():
        engine.register_node_type(node_class)

    for node_class in nodes.get_all_node_types():
        assert node_class.__name__ in engine.node_types
