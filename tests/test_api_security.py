"""API security tests for the Flask server.

Covers Phase 1 fixes:
- 1.1: /api/upload/file path traversal protection (directory allowlist)
- 1.2: /api/nodes/<node_id>/<action> only invokes declared node actions

Uses the sandboxed per-test app from conftest's ``api_client`` fixture: the
app is built via ``create_app`` with every persistence/upload path pointing
into tmp_path, so the real workflows/ dir is never touched.
"""

import io
import os

import pytest


@pytest.fixture
def client(api_client):
    """Flask test client with disk persistence and upload base sandboxed."""
    return api_client


@pytest.fixture
def workflow_id(client):
    """Create a fresh workflow (with started deployed engine) via the API."""
    resp = client.post('/api/workflows', json={'name': 'security test wf'})
    assert resp.status_code == 201
    return resp.get_json()['id']


def _upload(client, directory, filename='payload.txt', content=b'hello'):
    data = {'file': (io.BytesIO(content), filename)}
    if directory is not None:
        data['directory'] = directory
    return client.post('/api/upload/file', data=data,
                       content_type='multipart/form-data')


# ------------------------------------------------------------------
# 1.1 Upload path traversal
# ------------------------------------------------------------------

class TestUploadDirectoryValidation:

    def test_relative_traversal_rejected(self, client, tmp_path):
        resp = _upload(client, '../../evil', filename='evil.txt')
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False
        assert 'error' in body
        # Nothing escaped the sandbox: no file written anywhere under tmp_path
        assert list(tmp_path.rglob('evil.txt')) == []
        assert not (tmp_path / 'evil').exists()

    def test_absolute_path_rejected(self, client, tmp_path):
        target = tmp_path / 'abs_evil'
        resp = _upload(client, str(target), filename='evil.txt')
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False
        assert not target.exists()

    def test_sneaky_traversal_via_allowed_prefix_rejected(self, client, tmp_path):
        resp = _upload(client, 'models/../..', filename='evil.txt')
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False
        assert list(tmp_path.rglob('evil.txt')) == []

    def test_non_allowlisted_subdir_rejected(self, client, tmp_path):
        resp = _upload(client, 'static', filename='evil.txt')
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_models_upload_succeeds(self, client, tmp_path):
        resp = _upload(client, 'models', filename='model.onnx',
                       content=b'model-bytes')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        expected = tmp_path / 'upload_base' / 'models' / 'model.onnx'
        assert expected.is_file()
        assert expected.read_bytes() == b'model-bytes'
        assert body['filename'] == 'model.onnx'

    def test_default_directory_is_models(self, client, tmp_path):
        resp = _upload(client, None, filename='default.txt')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        assert (tmp_path / 'upload_base' / 'models' / 'default.txt').is_file()

    def test_filename_is_basenamed(self, client, tmp_path):
        resp = _upload(client, 'models', filename='../../escape.txt')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        # File must land inside models/ under its basename
        assert (tmp_path / 'upload_base' / 'models' / 'escape.txt').is_file()
        assert not (tmp_path / 'escape.txt').exists()


# ------------------------------------------------------------------
# 1.2 Node action allowlist
# ------------------------------------------------------------------

@pytest.fixture
def deployed_inject_node(client, workflow_id):
    """Create an InjectNode directly in the deployed engine of the workflow."""
    engine = client.manager.deployed_engines[workflow_id]
    node = engine.create_node('InjectNode', None, 'inject test', {})
    yield node
    engine.delete_node(node.id)


class TestNodeActionAllowlist:

    def test_declared_action_succeeds(self, client, deployed_inject_node):
        resp = client.post(f'/api/nodes/{deployed_inject_node.id}/inject')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['status'] == 'success'
        assert body['action'] == 'inject'

    def test_undeclared_public_method_rejected(self, client, deployed_inject_node):
        # on_stop is a real callable on every node but is not a declared action
        resp = client.post(f'/api/nodes/{deployed_inject_node.id}/on_stop')
        assert resp.status_code == 404

    def test_private_method_rejected(self, client, deployed_inject_node):
        resp = client.post(f'/api/nodes/{deployed_inject_node.id}/_start_worker')
        assert resp.status_code == 404

    def test_configure_rejected(self, client, deployed_inject_node):
        resp = client.post(f'/api/nodes/{deployed_inject_node.id}/configure')
        assert resp.status_code == 404

    def test_unknown_node_returns_404(self, client, workflow_id):
        resp = client.post('/api/nodes/no-such-node/inject')
        assert resp.status_code == 404


def test_frontend_actions_are_declared():
    """Every action name the frontend/UI can post must be declared."""
    from pynode.nodes.InjectNode.inject_node import InjectNode
    from pynode.nodes.CounterNode.counter_node import CounterNode
    from pynode.nodes.MessageWriterNode.messagereader_node import MessageReaderNode

    assert 'inject' in InjectNode.actions
    assert 'reset_counter' in CounterNode.actions
    assert 'read_files' in MessageReaderNode.actions

    for cls, action in ((InjectNode, 'inject'),
                        (CounterNode, 'reset_counter'),
                        (MessageReaderNode, 'read_files')):
        assert callable(getattr(cls, action))
