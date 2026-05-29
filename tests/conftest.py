"""Shared pytest fixtures and lightweight test node definitions.

These helper nodes deliberately avoid heavy dependencies (OpenCV, model
backends, etc.) so the core engine, registration and serialization behavior
can be exercised in isolation.
"""

import pytest

from pynode.nodes.base_node import BaseNode
from pynode.workflow_engine import WorkflowEngine


class _SourceNode(BaseNode):
    """A simple node with a single output used to emit messages."""

    input_count = 0
    output_count = 1


class _PassThroughNode(BaseNode):
    """Default pass-through node (one input, one output)."""

    input_count = 1
    output_count = 1


class _SinkNode(BaseNode):
    """A sink node (no outputs) that records messages synchronously.

    Because ``output_count == 0`` and it defines ``on_input_direct``, the
    engine delivers messages synchronously via ``BaseNode.send`` which keeps
    tests deterministic without relying on worker-thread timing.
    """

    input_count = 1
    output_count = 0

    def __init__(self, node_id=None, name=""):
        super().__init__(node_id=node_id, name=name)
        self.received = []

    def on_input_direct(self, msg, input_index=0):
        self.received.append(msg)


@pytest.fixture
def engine():
    """A WorkflowEngine pre-registered with the lightweight test nodes."""
    eng = WorkflowEngine()
    eng.register_node_type(_SourceNode)
    eng.register_node_type(_PassThroughNode)
    eng.register_node_type(_SinkNode)
    return eng


@pytest.fixture
def node_classes():
    """Expose the test node classes for direct use in tests."""
    return {
        'source': _SourceNode,
        'passthrough': _PassThroughNode,
        'sink': _SinkNode,
    }
