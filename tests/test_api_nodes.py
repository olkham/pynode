"""Flask API tests: node CRUD within a workflow, position, enabled state and
connection create/delete.

Uses the sandboxed ``api_client`` fixture from conftest.py (no disk writes,
empty state per test, engines stopped on teardown).
"""

import pytest


@pytest.fixture
def wf(api_client):
    """A fresh workflow id (becomes the active workflow)."""
    resp = api_client.post('/api/workflows', json={'name': 'node test wf'})
    assert resp.status_code == 201
    return resp.get_json()['id']


def _post_node(client, body, workflow=None):
    url = '/api/nodes' if workflow is None else f'/api/nodes?workflow={workflow}'
    return client.post(url, json=body)


# ------------------------------------------------------------------
# Node creation
# ------------------------------------------------------------------

class TestCreateNode:

    def test_create_node_201_shape(self, api_client, wf):
        resp = _post_node(api_client, {
            'type': 'DebugNode', 'name': 'my debug',
            'config': {'complete': 'payload'}, 'x': 100, 'y': 200,
        })
        assert resp.status_code == 201
        body = resp.get_json()
        assert body['type'] == 'DebugNode'
        assert body['name'] == 'my debug'
        assert body['config']['complete'] == 'payload'
        assert body['enabled'] is True
        assert 'id' in body
        assert 'inputCount' in body and 'outputCount' in body
        # Node lives in the working engine of the active workflow
        node = api_client.manager.working_engines[wf].get_node(body['id'])
        assert node is not None
        assert node.x == 100 and node.y == 200

    def test_create_node_defaults_to_active_workflow(self, api_client, wf):
        # Create a second, non-active workflow
        wid2 = api_client.post('/api/workflows',
                               json={'name': 'other wf'}).get_json()['id']
        resp = _post_node(api_client, {'type': 'InjectNode', 'name': 'n'})
        node_id = resp.get_json()['id']
        assert api_client.manager.working_engines[wf].get_node(node_id) is not None
        assert api_client.manager.working_engines[wid2].get_node(node_id) is None

    def test_create_node_with_workflow_param(self, api_client, wf):
        wid2 = api_client.post('/api/workflows',
                               json={'name': 'target wf'}).get_json()['id']
        resp = _post_node(api_client, {'type': 'InjectNode', 'name': 'n'},
                          workflow=wid2)
        node_id = resp.get_json()['id']
        assert api_client.manager.working_engines[wid2].get_node(node_id) is not None
        assert api_client.manager.working_engines[wf].get_node(node_id) is None

    def test_create_node_explicit_id(self, api_client, wf):
        resp = _post_node(api_client, {'type': 'DebugNode', 'id': 'fixed-id'})
        assert resp.get_json()['id'] == 'fixed-id'

    def test_unknown_node_type_400_json(self, api_client, wf):
        resp = _post_node(api_client, {'type': 'NoSuchNodeType'})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False
        assert 'NoSuchNodeType' in body['error']

    def test_create_node_unknown_workflow_404(self, api_client, wf):
        resp = _post_node(api_client, {'type': 'DebugNode'},
                          workflow='missing')
        assert resp.status_code == 404


# ------------------------------------------------------------------
# Node read
# ------------------------------------------------------------------

class TestGetNodes:

    def test_get_all_nodes(self, api_client, wf):
        id1 = _post_node(api_client, {'type': 'InjectNode'}).get_json()['id']
        id2 = _post_node(api_client, {'type': 'DebugNode'}).get_json()['id']
        resp = api_client.get('/api/nodes')
        assert resp.status_code == 200
        nodes = resp.get_json()
        assert {n['id'] for n in nodes} == {id1, id2}

    def test_get_single_node(self, api_client, wf):
        node_id = _post_node(api_client, {'type': 'DebugNode',
                                          'name': 'the one'}).get_json()['id']
        resp = api_client.get(f'/api/nodes/{node_id}')
        assert resp.status_code == 200
        assert resp.get_json()['name'] == 'the one'

    def test_get_unknown_node_404(self, api_client, wf):
        resp = api_client.get('/api/nodes/no-such-node')
        assert resp.status_code == 404
        assert resp.get_json()['success'] is False


# ------------------------------------------------------------------
# Node update (PUT /api/nodes/<id> and /position)
# ------------------------------------------------------------------

class TestUpdateNode:

    def test_update_name(self, api_client, wf):
        node_id = _post_node(api_client, {'type': 'DebugNode',
                                          'name': 'before'}).get_json()['id']
        resp = api_client.put(f'/api/nodes/{node_id}', json={'name': 'after'})
        assert resp.status_code == 200
        assert resp.get_json()['name'] == 'after'
        assert api_client.manager.working_engines[wf].get_node(node_id).name == 'after'

    def test_update_config_merges(self, api_client, wf):
        node_id = _post_node(api_client, {
            'type': 'DebugNode', 'config': {'complete': 'payload'},
        }).get_json()['id']
        resp = api_client.put(f'/api/nodes/{node_id}',
                              json={'config': {'console': False}})
        assert resp.status_code == 200
        cfg = resp.get_json()['config']
        assert cfg['console'] is False
        assert cfg['complete'] == 'payload'  # existing keys preserved

    def test_update_enabled(self, api_client, wf):
        node_id = _post_node(api_client, {'type': 'DebugNode'}).get_json()['id']
        resp = api_client.put(f'/api/nodes/{node_id}', json={'enabled': False})
        assert resp.status_code == 200
        assert resp.get_json()['enabled'] is False
        assert api_client.manager.working_engines[wf].get_node(node_id).enabled is False

    def test_update_unknown_node_404(self, api_client, wf):
        resp = api_client.put('/api/nodes/ghost', json={'name': 'x'})
        assert resp.status_code == 404

    def test_update_position(self, api_client, wf):
        node_id = _post_node(api_client, {'type': 'DebugNode',
                                          'x': 1, 'y': 2}).get_json()['id']
        resp = api_client.put(f'/api/nodes/{node_id}/position',
                              json={'x': 300, 'y': 400})
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        node = api_client.manager.working_engines[wf].get_node(node_id)
        assert node.x == 300 and node.y == 400

    def test_update_position_unknown_node_404(self, api_client, wf):
        resp = api_client.put('/api/nodes/ghost/position',
                              json={'x': 1, 'y': 1})
        assert resp.status_code == 404


# ------------------------------------------------------------------
# Node delete
# ------------------------------------------------------------------

class TestDeleteNode:

    def test_delete_node_204(self, api_client, wf):
        node_id = _post_node(api_client, {'type': 'DebugNode'}).get_json()['id']
        resp = api_client.delete(f'/api/nodes/{node_id}')
        assert resp.status_code == 204
        assert api_client.manager.working_engines[wf].get_node(node_id) is None
        assert api_client.get(f'/api/nodes/{node_id}').status_code == 404

    def test_delete_removes_inbound_connections(self, api_client, wf):
        src = _post_node(api_client, {'type': 'InjectNode'}).get_json()['id']
        dst = _post_node(api_client, {'type': 'DebugNode'}).get_json()['id']
        api_client.post('/api/connections', json={'source': src, 'target': dst})

        api_client.delete(f'/api/nodes/{dst}')

        export = api_client.get('/api/workflow').get_json()
        assert export['connections'] == []


# ------------------------------------------------------------------
# Connections
# ------------------------------------------------------------------

class TestConnections:

    def test_create_connection_201(self, api_client, wf):
        src = _post_node(api_client, {'type': 'InjectNode'}).get_json()['id']
        dst = _post_node(api_client, {'type': 'DebugNode'}).get_json()['id']
        resp = api_client.post('/api/connections', json={
            'source': src, 'target': dst,
            'sourceOutput': 0, 'targetInput': 0,
        })
        assert resp.status_code == 201
        assert resp.get_json() == {'source': src, 'target': dst,
                                   'sourceOutput': 0, 'targetInput': 0}
        export = api_client.get('/api/workflow').get_json()
        assert export['connections'] == [{'source': src, 'target': dst,
                                          'sourceOutput': 0, 'targetInput': 0}]

    def test_connect_missing_node_400(self, api_client, wf):
        src = _post_node(api_client, {'type': 'InjectNode'}).get_json()['id']
        resp = api_client.post('/api/connections',
                               json={'source': src, 'target': 'ghost'})
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_connect_missing_source_400(self, api_client, wf):
        dst = _post_node(api_client, {'type': 'DebugNode'}).get_json()['id']
        resp = api_client.post('/api/connections',
                               json={'source': 'ghost', 'target': dst})
        assert resp.status_code == 400

    def test_delete_connection_204(self, api_client, wf):
        src = _post_node(api_client, {'type': 'InjectNode'}).get_json()['id']
        dst = _post_node(api_client, {'type': 'DebugNode'}).get_json()['id']
        api_client.post('/api/connections', json={'source': src, 'target': dst})

        resp = api_client.delete('/api/connections', json={
            'source': src, 'target': dst, 'sourceOutput': 0,
        })
        assert resp.status_code == 204
        export = api_client.get('/api/workflow').get_json()
        assert export['connections'] == []

    def test_delete_connection_missing_node_400(self, api_client, wf):
        resp = api_client.delete('/api/connections',
                                 json={'source': 'ghost', 'target': 'ghost2'})
        assert resp.status_code == 400


# ------------------------------------------------------------------
# Node enabled endpoints (POST/GET /api/nodes/<id>/enabled)
# ------------------------------------------------------------------

class TestNodeEnabledEndpoints:

    def test_set_and_get_enabled_across_engines(self, api_client, wf):
        node_id = _post_node(api_client, {'type': 'DebugNode'}).get_json()['id']
        # Deploy so the node exists in both working and deployed engines
        api_client.post('/api/workflow/save')

        resp = api_client.post(f'/api/nodes/{node_id}/enabled',
                               json={'enabled': False})
        assert resp.status_code == 200
        assert resp.get_json() == {'success': True, 'enabled': False}
        assert api_client.manager.working_engines[wf].get_node(node_id).enabled is False
        assert api_client.manager.deployed_engines[wf].get_node(node_id).enabled is False

        resp = api_client.get(f'/api/nodes/{node_id}/enabled')
        assert resp.status_code == 200
        assert resp.get_json() == {'enabled': False}

    def test_get_enabled_unknown_node_404(self, api_client, wf):
        resp = api_client.get('/api/nodes/ghost/enabled')
        assert resp.status_code == 404
