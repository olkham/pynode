"""Tests for Phase 2.4: standardized JSON API error contract.

Every error response must be JSON shaped {'success': False, 'error': str} -
never Flask's default HTML error pages, including for malformed bodies,
unknown routes and wrong methods.
"""

import pytest

import pynode.server as server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'save_workflow_to_disk', lambda: None)
    monkeypatch.setattr(server, 'WORKFLOWS_DIR', str(tmp_path / 'workflows'))
    monkeypatch.setattr(server, 'WORKFLOW_FILE',
                        str(tmp_path / 'workflows' / 'workflow.json'))
    server.app.config['TESTING'] = True
    with server.app.test_client() as c:
        yield c


def _assert_json_error(resp, status):
    assert resp.status_code == status
    assert resp.mimetype == 'application/json'
    body = resp.get_json()
    assert body is not None, 'response body is not JSON'
    assert body['success'] is False
    assert isinstance(body['error'], str) and body['error']


class TestMalformedJsonBodies:

    def test_create_node_malformed_json(self, client):
        resp = client.post('/api/nodes', data='{not valid json',
                           content_type='application/json')
        _assert_json_error(resp, 400)

    def test_create_node_wrong_content_type(self, client):
        resp = client.post('/api/nodes', data='plain text body',
                           content_type='text/plain')
        _assert_json_error(resp, 400)

    def test_create_node_missing_body(self, client):
        resp = client.post('/api/nodes')
        _assert_json_error(resp, 400)

    def test_create_node_non_object_json(self, client):
        resp = client.post('/api/nodes', data='[1, 2, 3]',
                           content_type='application/json')
        _assert_json_error(resp, 400)

    def test_create_workflow_malformed_json(self, client):
        resp = client.post('/api/workflows', data='{not valid json',
                           content_type='application/json')
        _assert_json_error(resp, 400)

    def test_create_workflow_no_body_still_works(self, client):
        # Body is optional for workflow creation (defaults the name)
        resp = client.post('/api/workflows')
        assert resp.status_code == 201
        assert 'id' in resp.get_json()

    def test_set_active_workflow_malformed_json(self, client):
        resp = client.put('/api/workflows/active', data='{{{{',
                          content_type='application/json')
        _assert_json_error(resp, 400)

    def test_connection_malformed_json(self, client):
        resp = client.post('/api/connections', data='not json at all',
                           content_type='application/json')
        _assert_json_error(resp, 400)


class TestErrorEnvelopes:

    def test_unknown_api_route_is_json_404(self, client):
        resp = client.get('/api/definitely-not-a-route')
        _assert_json_error(resp, 404)

    def test_wrong_method_is_json_405(self, client):
        resp = client.delete('/api/node-types')
        _assert_json_error(resp, 405)

    def test_unknown_workflow_is_json_404(self, client):
        resp = client.get('/api/nodes?workflow=no_such_workflow')
        _assert_json_error(resp, 404)

    def test_create_node_unknown_type_is_json_400(self, client):
        client.post('/api/workflows', json={'name': 'err contract wf'})
        resp = client.post('/api/nodes', json={'type': 'NoSuchNodeType'})
        _assert_json_error(resp, 400)

    def test_error_key_preserved_for_frontend(self, client):
        """The frontend reads `.error`; the envelope must keep that key."""
        resp = client.get('/api/nodes?workflow=no_such_workflow')
        body = resp.get_json()
        assert 'error' in body
        assert body['success'] is False
