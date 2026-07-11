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
def api_app(tmp_path):
    """A fresh, fully sandboxed Flask app built via ``create_app``.

    - Every persistence/upload path points into tmp_path, so the real
      workflows/ dir is never touched.
    - The app has its own WorkflowManager (empty workflow state) and its own
      SSE broadcast state - nothing is shared with other tests or with the
      module-level default app.
    - Teardown calls ``manager.shutdown()`` so every deployed engine (and its
      worker threads) plus the SSE broadcast thread is stopped/joined before
      the test's tmp_path fixtures are torn down.
    """
    from pynode.server import create_app

    upload_base = tmp_path / 'upload_base'
    upload_base.mkdir()
    application = create_app({
        'WORKFLOWS_DIR': str(tmp_path / 'workflows'),
        'WORKFLOW_FILE': str(tmp_path / 'workflows' / 'workflow.json'),
        'UPLOAD_BASE_DIR': str(upload_base),
        'TESTING': True,
    })
    yield application
    application.extensions['workflow_manager'].shutdown()


@pytest.fixture
def manager(api_app):
    """The WorkflowManager owned by the app under test."""
    return api_app.extensions['workflow_manager']


@pytest.fixture
def api_client(api_app, manager):
    """Flask test client for the sandboxed per-test app.

    The client also exposes ``api_client.manager`` (the app's
    WorkflowManager) so tests can assert on engine/workflow state directly.
    """
    with api_app.test_client() as c:
        c.manager = manager
        yield c


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
