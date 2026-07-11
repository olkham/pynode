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
def isolated_workflow_state():
    """Snapshot, clear and restore pynode.server's module-global workflow state.

    Keeps tests that exercise the real save/load/deploy paths from seeing (or
    perturbing) workflows accumulated by other test modules in this process.
    """
    import pynode.server as server

    with server._state_lock:
        saved_workflows = dict(server._workflows)
        saved_working = dict(server._working_engines)
        saved_deployed = dict(server._deployed_engines)
        saved_active = server._active_workflow_id
        server._workflows.clear()
        server._working_engines.clear()
        server._deployed_engines.clear()
        server._active_workflow_id = None
    yield
    with server._state_lock:
        # Stop any engines the test started before dropping them
        for eng in server._deployed_engines.values():
            try:
                eng.stop()
            except Exception:
                pass
        server._workflows.clear()
        server._workflows.update(saved_workflows)
        server._working_engines.clear()
        server._working_engines.update(saved_working)
        server._deployed_engines.clear()
        server._deployed_engines.update(saved_deployed)
        server._active_workflow_id = saved_active


@pytest.fixture
def api_client(tmp_path, monkeypatch, isolated_workflow_state):
    """Flask test client with fully sandboxed, empty workflow state.

    - Disk persistence is disabled (save_workflow_to_disk is a no-op) and all
      path globals point into tmp_path, so the real workflows/ dir is never
      touched.
    - ``isolated_workflow_state`` guarantees each test starts with zero
      workflows and that any engines (and their worker threads) started during
      the test are stopped on teardown.
    """
    import pynode.server as server

    monkeypatch.setattr(server, 'save_workflow_to_disk', lambda: None)
    monkeypatch.setattr(server, 'WORKFLOWS_DIR', str(tmp_path / 'workflows'))
    monkeypatch.setattr(server, 'WORKFLOW_FILE',
                        str(tmp_path / 'workflows' / 'workflow.json'))
    upload_base = tmp_path / 'upload_base'
    upload_base.mkdir()
    monkeypatch.setattr(server, 'UPLOAD_BASE_DIR', str(upload_base))

    server.app.config['TESTING'] = True
    with server.app.test_client() as c:
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
