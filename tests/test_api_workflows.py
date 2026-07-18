"""Flask API tests: workflow CRUD, active switching, export/import,
save (full deploy), deploy-changes (incremental deploy) and stats.

Uses the sandboxed ``api_client`` fixture from conftest.py: no disk writes,
empty workflow state per test, engines stopped on teardown. Only
dependency-light node types (DebugNode, InjectNode, ChangeNode) are used.
"""



def _create_wf(client, name):
    resp = client.post('/api/workflows', json={'name': name})
    assert resp.status_code == 201
    return resp.get_json()['id']


def _add_node(client, wid, node_type='DebugNode', name='', node_id=None,
              config=None, x=None, y=None):
    body = {'type': node_type, 'name': name, 'config': config or {}}
    if node_id is not None:
        body['id'] = node_id
    if x is not None:
        body['x'] = x
    if y is not None:
        body['y'] = y
    resp = client.post(f'/api/nodes?workflow={wid}', json=body)
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


# ------------------------------------------------------------------
# Workflow CRUD
# ------------------------------------------------------------------

class TestWorkflowCrud:

    def test_create_returns_201_with_metadata(self, api_client):
        resp = api_client.post('/api/workflows', json={'name': 'wf one'})
        assert resp.status_code == 201
        body = resp.get_json()
        assert body['name'] == 'wf one'
        assert body['enabled'] is True
        wid = body['id']
        # Working + deployed engines exist; deployed engine is started
        assert wid in api_client.manager.working_engines
        assert api_client.manager.deployed_engines[wid].running is True
        assert api_client.manager.working_engines[wid].running is False

    def test_create_duplicate_name_gets_unique_suffix(self, api_client):
        _create_wf(api_client, 'dup wf')
        resp2 = api_client.post('/api/workflows', json={'name': 'dup wf'})
        resp3 = api_client.post('/api/workflows', json={'name': 'dup wf'})
        assert resp2.get_json()['name'] == 'dup wf (1)'
        assert resp3.get_json()['name'] == 'dup wf (2)'

    def test_rapid_creation_yields_unique_ids(self, api_client):
        """Regression: ms-timestamp ids collided when two workflows were
        created within the same millisecond, silently overwriting the first."""
        ids = [api_client.post('/api/workflows',
                               json={'name': f'rapid {i}'}).get_json()['id']
               for i in range(5)]
        assert len(set(ids)) == 5
        assert len(api_client.get('/api/workflows').get_json()) == 5

    def test_list_shape_includes_node_count_and_active(self, api_client):
        wid = _create_wf(api_client, 'list wf')
        _add_node(api_client, wid, 'DebugNode', 'd1')

        resp = api_client.get('/api/workflows')
        assert resp.status_code == 200
        items = resp.get_json()
        assert len(items) == 1
        entry = items[0]
        assert set(entry) == {'id', 'name', 'enabled', 'nodeCount', 'active',
                              'running'}
        assert entry['id'] == wid
        assert entry['name'] == 'list wf'
        assert entry['enabled'] is True
        assert entry['nodeCount'] == 1
        assert entry['active'] is True  # first workflow becomes active
        assert entry['running'] is True  # deployed engine started on create

    def test_rename_via_put(self, api_client):
        wid = _create_wf(api_client, 'old name')
        resp = api_client.put(f'/api/workflows/{wid}', json={'name': 'new name'})
        assert resp.status_code == 200
        assert resp.get_json()['name'] == 'new name'
        assert api_client.manager.workflows[wid]['name'] == 'new name'

    def test_rename_collision_gets_suffix(self, api_client):
        _create_wf(api_client, 'taken')
        wid2 = _create_wf(api_client, 'other')
        resp = api_client.put(f'/api/workflows/{wid2}', json={'name': 'taken'})
        assert resp.get_json()['name'] == 'taken (1)'

    def test_disable_stops_and_enable_starts_deployed_engine(self, api_client):
        wid = _create_wf(api_client, 'toggle wf')
        deployed = api_client.manager.deployed_engines[wid]
        assert deployed.running is True

        resp = api_client.put(f'/api/workflows/{wid}', json={'enabled': False})
        assert resp.status_code == 200
        assert resp.get_json()['enabled'] is False
        assert deployed.running is False

        resp = api_client.put(f'/api/workflows/{wid}', json={'enabled': True})
        assert resp.get_json()['enabled'] is True
        assert deployed.running is True

    def test_update_unknown_workflow_404(self, api_client):
        _create_wf(api_client, 'wf')
        resp = api_client.put('/api/workflows/no_such', json={'name': 'x'})
        assert resp.status_code == 404
        assert resp.get_json()['success'] is False

    def test_delete_workflow(self, api_client):
        wid1 = _create_wf(api_client, 'keep')
        wid2 = _create_wf(api_client, 'remove')
        deployed2 = api_client.manager.deployed_engines[wid2]

        resp = api_client.delete(f'/api/workflows/{wid2}')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['activeWorkflow'] == wid1
        assert wid2 not in api_client.manager.workflows
        assert wid2 not in api_client.manager.working_engines
        assert wid2 not in api_client.manager.deployed_engines
        assert deployed2.running is False  # engine was stopped

    def test_delete_active_workflow_switches_active(self, api_client):
        wid1 = _create_wf(api_client, 'first')  # active
        wid2 = _create_wf(api_client, 'second')
        resp = api_client.delete(f'/api/workflows/{wid1}')
        assert resp.status_code == 200
        assert resp.get_json()['activeWorkflow'] == wid2
        assert api_client.manager.active_workflow_id == wid2

    def test_delete_last_workflow_rejected_400(self, api_client):
        wid = _create_wf(api_client, 'only one')
        resp = api_client.delete(f'/api/workflows/{wid}')
        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False
        assert 'last' in body['error'].lower()
        assert wid in api_client.manager.workflows  # still there

    def test_delete_unknown_workflow_404(self, api_client):
        _create_wf(api_client, 'wf')
        resp = api_client.delete('/api/workflows/no_such')
        assert resp.status_code == 404


# ------------------------------------------------------------------
# Active workflow switching
# ------------------------------------------------------------------

class TestActiveWorkflow:

    def test_switch_active(self, api_client):
        wid1 = _create_wf(api_client, 'a')
        wid2 = _create_wf(api_client, 'b')
        assert api_client.manager.active_workflow_id == wid1

        resp = api_client.put('/api/workflows/active', json={'workflowId': wid2})
        assert resp.status_code == 200
        assert resp.get_json() == {'success': True, 'activeWorkflow': wid2}
        assert api_client.manager.active_workflow_id == wid2

        actives = {w['id']: w['active'] for w in
                   api_client.get('/api/workflows').get_json()}
        assert actives == {wid1: False, wid2: True}

    def test_switch_to_unknown_id_404(self, api_client):
        _create_wf(api_client, 'a')
        resp = api_client.put('/api/workflows/active',
                              json={'workflowId': 'nope'})
        assert resp.status_code == 404
        assert resp.get_json()['success'] is False


# ------------------------------------------------------------------
# GET /api/workflow (working export) and /api/workflow/deployed
# ------------------------------------------------------------------

class TestWorkflowExport:

    def test_get_workflow_export_shape(self, api_client):
        wid = _create_wf(api_client, 'export wf')
        n1 = _add_node(api_client, wid, 'InjectNode', 'src', x=10, y=20)
        n2 = _add_node(api_client, wid, 'DebugNode', 'dst')
        api_client.post(f'/api/connections?workflow={wid}',
                        json={'source': n1['id'], 'target': n2['id']})

        resp = api_client.get(f'/api/workflow?workflow={wid}')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['id'] == wid
        assert body['name'] == 'export wf'
        assert body['enabled'] is True
        assert {n['id'] for n in body['nodes']} == {n1['id'], n2['id']}
        node1 = next(n for n in body['nodes'] if n['id'] == n1['id'])
        assert node1['type'] == 'InjectNode'
        assert node1['x'] == 10 and node1['y'] == 20
        assert body['connections'] == [{
            'source': n1['id'], 'target': n2['id'],
            'sourceOutput': 0, 'targetInput': 0,
        }]

    def test_get_workflow_unknown_id_404(self, api_client):
        _create_wf(api_client, 'wf')
        resp = api_client.get('/api/workflow?workflow=missing')
        assert resp.status_code == 404

    def test_get_deployed_workflow(self, api_client):
        wid = _create_wf(api_client, 'deployed wf')
        # Working-only node must NOT appear in the deployed export
        _add_node(api_client, wid, 'DebugNode', 'undeployed')
        resp = api_client.get(f'/api/workflow/deployed?workflow={wid}')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['nodes'] == []
        assert body['connections'] == []


# ------------------------------------------------------------------
# POST /api/workflow (import)
# ------------------------------------------------------------------

class TestWorkflowImport:

    def test_import_replaces_working_and_deployed_and_starts(self, api_client):
        wid = _create_wf(api_client, 'import wf')
        # Pre-existing working node should be wiped by import
        old = _add_node(api_client, wid, 'DebugNode', 'old-node')

        data = {
            'nodes': [
                {'id': 'imp-src', 'type': 'InjectNode', 'name': 'source',
                 'config': {}, 'enabled': True, 'x': 1, 'y': 2},
                {'id': 'imp-dst', 'type': 'DebugNode', 'name': 'sink',
                 'config': {}, 'enabled': True, 'x': 3, 'y': 4},
            ],
            'connections': [
                {'source': 'imp-src', 'target': 'imp-dst',
                 'sourceOutput': 0, 'targetInput': 0},
            ],
        }
        resp = api_client.post(f'/api/workflow?workflow={wid}', json=data)
        assert resp.status_code == 201
        body = resp.get_json()
        assert body['id'] == wid
        assert {n['id'] for n in body['nodes']} == {'imp-src', 'imp-dst'}

        working = api_client.manager.working_engines[wid]
        deployed = api_client.manager.deployed_engines[wid]
        for eng in (working, deployed):
            assert eng.get_node('imp-src') is not None
            assert eng.get_node('imp-dst') is not None
            assert eng.get_node(old['id']) is None
        # Workflow is enabled, so the deployed engine restarts after import
        assert deployed.running is True

    def test_import_into_disabled_workflow_does_not_start(self, api_client):
        wid = _create_wf(api_client, 'disabled import wf')
        api_client.put(f'/api/workflows/{wid}', json={'enabled': False})

        data = {'nodes': [{'id': 'n1', 'type': 'DebugNode', 'name': 'd',
                           'config': {}, 'enabled': True}],
                'connections': []}
        resp = api_client.post(f'/api/workflow?workflow={wid}', json=data)
        assert resp.status_code == 201
        assert api_client.manager.deployed_engines[wid].running is False


# ------------------------------------------------------------------
# POST /api/workflow/save (full deploy)
# ------------------------------------------------------------------

class TestWorkflowSave:

    def test_save_deploys_working_changes_to_deployed(self, api_client):
        wid = _create_wf(api_client, 'save wf')
        node = _add_node(api_client, wid, 'ChangeNode', 'ch',
                         config={'rules': []})
        deployed = api_client.manager.deployed_engines[wid]
        assert deployed.get_node(node['id']) is None  # not deployed yet

        resp = api_client.post('/api/workflow/save')
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        assert deployed.get_node(node['id']) is not None
        assert deployed.running is True

    def test_save_applies_working_config_changes(self, api_client):
        wid = _create_wf(api_client, 'save cfg wf')
        node = _add_node(api_client, wid, 'DebugNode', 'dbg')
        api_client.post('/api/workflow/save')

        # Change config in the WORKING engine only
        resp = api_client.put(f'/api/nodes/{node["id"]}?workflow={wid}',
                              json={'config': {'complete': 'true'}})
        assert resp.status_code == 200
        deployed_node = api_client.manager.deployed_engines[wid].get_node(node['id'])
        assert deployed_node.config.get('complete') != 'true'

        api_client.post('/api/workflow/save')

        deployed_node = api_client.manager.deployed_engines[wid].get_node(node['id'])
        assert deployed_node is not None
        assert deployed_node.config['complete'] == 'true'


# ------------------------------------------------------------------
# POST /api/workflow/deploy-changes (incremental deploy)
# ------------------------------------------------------------------

class TestDeployChanges:

    def test_missing_body_400(self, api_client):
        _create_wf(api_client, 'dc wf')
        resp = api_client.post('/api/workflow/deploy-changes')
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_added_nodes(self, api_client):
        wid = _create_wf(api_client, 'dc add wf')
        resp = api_client.post('/api/workflow/deploy-changes', json={
            'workflowId': wid,
            'addedNodes': [{'id': 'add-1', 'type': 'DebugNode',
                            'name': 'added', 'config': {}, 'enabled': True,
                            'x': 5, 'y': 6}],
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['nodesRestarted'] == 1

        for eng in (api_client.manager.working_engines[wid], api_client.manager.deployed_engines[wid]):
            node = eng.get_node('add-1')
            assert node is not None
            assert node.name == 'added'
            assert node.x == 5 and node.y == 6

    def test_modified_nodes_config_applied_to_deployed(self, api_client):
        wid = _create_wf(api_client, 'dc mod wf')
        api_client.post('/api/workflow/deploy-changes', json={
            'workflowId': wid,
            'addedNodes': [{'id': 'mod-1', 'type': 'DebugNode',
                            'name': 'before', 'config': {}, 'enabled': True}],
        })

        resp = api_client.post('/api/workflow/deploy-changes', json={
            'workflowId': wid,
            'modifiedNodes': [{'id': 'mod-1', 'name': 'after',
                               'config': {'complete': 'payload.thing'},
                               'enabled': True, 'x': 9, 'y': 8}],
        })
        assert resp.status_code == 200
        assert resp.get_json()['nodesRestarted'] == 1

        deployed_node = api_client.manager.deployed_engines[wid].get_node('mod-1')
        assert deployed_node.name == 'after'
        assert deployed_node.config['complete'] == 'payload.thing'
        working_node = api_client.manager.working_engines[wid].get_node('mod-1')
        assert working_node.name == 'after'
        assert working_node.config['complete'] == 'payload.thing'

    def test_deleted_nodes(self, api_client):
        wid = _create_wf(api_client, 'dc del wf')
        api_client.post('/api/workflow/deploy-changes', json={
            'workflowId': wid,
            'addedNodes': [{'id': 'del-1', 'type': 'DebugNode',
                            'name': 'doomed', 'config': {}, 'enabled': True}],
        })
        resp = api_client.post('/api/workflow/deploy-changes', json={
            'workflowId': wid,
            'deletedNodes': ['del-1'],
        })
        assert resp.status_code == 200
        assert api_client.manager.deployed_engines[wid].get_node('del-1') is None
        assert api_client.manager.working_engines[wid].get_node('del-1') is None

    def test_added_and_deleted_connections(self, api_client):
        wid = _create_wf(api_client, 'dc conn wf')
        api_client.post('/api/workflow/deploy-changes', json={
            'workflowId': wid,
            'addedNodes': [
                {'id': 'c-src', 'type': 'InjectNode', 'name': 's',
                 'config': {}, 'enabled': True},
                {'id': 'c-dst', 'type': 'DebugNode', 'name': 'd',
                 'config': {}, 'enabled': True},
            ],
        })

        conn = {'source': 'c-src', 'target': 'c-dst',
                'sourceOutput': 0, 'targetInput': 0}
        resp = api_client.post('/api/workflow/deploy-changes', json={
            'workflowId': wid, 'addedConnections': [conn],
        })
        assert resp.status_code == 200

        def connected(engine):
            src = engine.get_node('c-src')
            return any(t.id == 'c-dst'
                       for targets in src.outputs.values()
                       for t, _ in targets)

        assert connected(api_client.manager.deployed_engines[wid])
        assert connected(api_client.manager.working_engines[wid])

        resp = api_client.post('/api/workflow/deploy-changes', json={
            'workflowId': wid, 'deletedConnections': [conn],
        })
        assert resp.status_code == 200
        assert not connected(api_client.manager.deployed_engines[wid])
        assert not connected(api_client.manager.working_engines[wid])

    def test_unknown_workflow_404(self, api_client):
        _create_wf(api_client, 'dc wf')
        resp = api_client.post('/api/workflow/deploy-changes',
                               json={'workflowId': 'nope', 'addedNodes': []})
        assert resp.status_code == 404


# ------------------------------------------------------------------
# POST /api/workflow/stop (transient stop of all deployed engines)
# ------------------------------------------------------------------

class TestWorkflowStop:

    def test_stop_halts_all_deployed_engines_without_persisting(
            self, api_client, monkeypatch):
        wid1 = _create_wf(api_client, 'stop wf 1')
        wid2 = _create_wf(api_client, 'stop wf 2')
        manager = api_client.manager
        assert manager.deployed_engines[wid1].running is True
        assert manager.deployed_engines[wid2].running is True

        # Spy on disk persistence: a transient stop must never save.
        save_calls = []
        monkeypatch.setattr(manager, 'save_workflow_to_disk',
                            lambda *a, **k: save_calls.append(1))

        resp = api_client.post('/api/workflow/stop')
        assert resp.status_code == 200
        assert resp.get_json() == {'success': True, 'stopped': 2}

        # Engines stopped, but 'enabled' flags untouched and nothing saved
        assert manager.deployed_engines[wid1].running is False
        assert manager.deployed_engines[wid2].running is False
        assert manager.workflows[wid1]['enabled'] is True
        assert manager.workflows[wid2]['enabled'] is True
        assert save_calls == []

        # The workflows list now reports running=False for both
        running = {w['id']: w['running'] for w in
                   api_client.get('/api/workflows').get_json()}
        assert running == {wid1: False, wid2: False}

    def test_full_deploy_after_stop_restarts_engines(self, api_client):
        wid = _create_wf(api_client, 'stop then save wf')
        api_client.post('/api/workflow/stop')
        assert api_client.manager.deployed_engines[wid].running is False

        resp = api_client.post('/api/workflow/save')
        assert resp.status_code == 200
        assert api_client.manager.deployed_engines[wid].running is True

    def test_deploy_changes_after_stop_restarts_engine(self, api_client):
        wid = _create_wf(api_client, 'stop then deploy wf')
        api_client.post('/api/workflow/stop')
        deployed = api_client.manager.deployed_engines[wid]
        assert deployed.running is False

        # Incremental deploy (even with a change set) must resume processing
        resp = api_client.post('/api/workflow/deploy-changes', json={
            'workflowId': wid,
            'addedNodes': [{'id': 'post-stop-1', 'type': 'DebugNode',
                            'name': 'added', 'config': {}, 'enabled': True}],
        })
        assert resp.status_code == 200
        assert deployed.running is True
        assert deployed.get_node('post-stop-1') is not None

        # Empty incremental deploy also resumes after another stop
        api_client.post('/api/workflow/stop')
        assert deployed.running is False
        resp = api_client.post('/api/workflow/deploy-changes',
                               json={'workflowId': wid})
        assert resp.status_code == 200
        assert deployed.running is True

    def test_deploy_changes_does_not_start_disabled_workflow(self, api_client):
        wid = _create_wf(api_client, 'disabled deploy wf')
        api_client.put(f'/api/workflows/{wid}', json={'enabled': False})
        deployed = api_client.manager.deployed_engines[wid]
        assert deployed.running is False

        resp = api_client.post('/api/workflow/deploy-changes',
                               json={'workflowId': wid})
        assert resp.status_code == 200
        assert deployed.running is False

    def test_stop_leaves_disabled_workflow_untouched(self, api_client):
        wid_on = _create_wf(api_client, 'enabled wf')
        wid_off = _create_wf(api_client, 'disabled wf')
        api_client.put(f'/api/workflows/{wid_off}', json={'enabled': False})
        manager = api_client.manager
        assert manager.deployed_engines[wid_off].running is False

        resp = api_client.post('/api/workflow/stop')
        assert resp.status_code == 200
        assert resp.get_json() == {'success': True, 'stopped': 1}
        assert manager.deployed_engines[wid_on].running is False
        assert manager.deployed_engines[wid_off].running is False
        assert manager.workflows[wid_off]['enabled'] is False

    def test_stop_twice_is_idempotent(self, api_client):
        _create_wf(api_client, 'idempotent stop wf')
        resp1 = api_client.post('/api/workflow/stop')
        assert resp1.status_code == 200
        assert resp1.get_json() == {'success': True, 'stopped': 1}

        resp2 = api_client.post('/api/workflow/stop')
        assert resp2.status_code == 200
        assert resp2.get_json() == {'success': True, 'stopped': 0}

    # ------------------------------------------------------------
    # Scoped stop: ?workflow=<id> affects only that one flow. This is what
    # the frontend's Deploy-menu "Stop" action now sends (see workflow.js
    # stopWorkflow) so stopping one tab's processing no longer stops every
    # other open tab too.
    # ------------------------------------------------------------

    def test_scoped_stop_only_halts_requested_workflow(self, api_client):
        wid1 = _create_wf(api_client, 'scoped stop wf 1')
        wid2 = _create_wf(api_client, 'scoped stop wf 2')
        manager = api_client.manager
        assert manager.deployed_engines[wid1].running is True
        assert manager.deployed_engines[wid2].running is True

        resp = api_client.post(f'/api/workflow/stop?workflow={wid1}')
        assert resp.status_code == 200
        assert resp.get_json() == {'success': True, 'stopped': 1}

        assert manager.deployed_engines[wid1].running is False
        assert manager.deployed_engines[wid2].running is True  # untouched

        running = {w['id']: w['running'] for w in
                   api_client.get('/api/workflows').get_json()}
        assert running == {wid1: False, wid2: True}

    def test_scoped_stop_unknown_workflow_404(self, api_client):
        _create_wf(api_client, 'scoped stop wf')
        resp = api_client.post('/api/workflow/stop?workflow=no_such')
        assert resp.status_code == 404
        assert resp.get_json()['success'] is False


# ------------------------------------------------------------------
# POST /api/workflow/restart (all vs. scoped)
# ------------------------------------------------------------------

class TestWorkflowRestart:

    def test_restart_all_restarts_every_enabled_engine(self, api_client):
        wid1 = _create_wf(api_client, 'restart wf 1')
        wid2 = _create_wf(api_client, 'restart wf 2')
        manager = api_client.manager
        api_client.post('/api/workflow/stop')
        assert manager.deployed_engines[wid1].running is False
        assert manager.deployed_engines[wid2].running is False

        resp = api_client.post('/api/workflow/restart')
        assert resp.status_code == 200
        assert resp.get_json() == {'success': True}
        assert manager.deployed_engines[wid1].running is True
        assert manager.deployed_engines[wid2].running is True

    def test_scoped_restart_only_restarts_requested_workflow(self, api_client):
        wid1 = _create_wf(api_client, 'scoped restart wf 1')
        wid2 = _create_wf(api_client, 'scoped restart wf 2')
        manager = api_client.manager
        api_client.post('/api/workflow/stop')  # stop both first
        assert manager.deployed_engines[wid1].running is False
        assert manager.deployed_engines[wid2].running is False

        resp = api_client.post(f'/api/workflow/restart?workflow={wid1}')
        assert resp.status_code == 200
        assert resp.get_json() == {'success': True}

        assert manager.deployed_engines[wid1].running is True
        assert manager.deployed_engines[wid2].running is False  # untouched

    def test_scoped_restart_does_not_start_disabled_workflow(self, api_client):
        wid = _create_wf(api_client, 'scoped restart disabled wf')
        api_client.put(f'/api/workflows/{wid}', json={'enabled': False})
        manager = api_client.manager
        assert manager.deployed_engines[wid].running is False

        resp = api_client.post(f'/api/workflow/restart?workflow={wid}')
        assert resp.status_code == 200
        assert manager.deployed_engines[wid].running is False

    def test_scoped_restart_unknown_workflow_404(self, api_client):
        _create_wf(api_client, 'scoped restart wf')
        resp = api_client.post('/api/workflow/restart?workflow=no_such')
        assert resp.status_code == 404
        assert resp.get_json()['success'] is False


# ------------------------------------------------------------------
# GET /api/workflow/stats
# ------------------------------------------------------------------

class TestWorkflowStats:

    def test_stats_shape(self, api_client):
        wid = _create_wf(api_client, 'stats wf')
        data = {
            'nodes': [
                {'id': 's1', 'type': 'InjectNode', 'name': 's',
                 'config': {}, 'enabled': True},
                {'id': 's2', 'type': 'DebugNode', 'name': 'd',
                 'config': {}, 'enabled': True},
            ],
            'connections': [{'source': 's1', 'target': 's2',
                             'sourceOutput': 0, 'targetInput': 0}],
        }
        api_client.post(f'/api/workflow?workflow={wid}', json=data)

        resp = api_client.get(f'/api/workflow/stats?workflow={wid}')
        assert resp.status_code == 200
        stats = resp.get_json()
        assert set(stats) == {'total_nodes', 'total_connections',
                              'node_types', 'running'}
        assert stats['running'] is True
        assert stats['total_connections'] == 1
        # The deployed engine also contains the hidden __system_error__
        # ErrorNode while running, but system nodes are excluded from stats.
        assert stats['total_nodes'] == 2
        assert stats['node_types'] == {'InjectNode': 1, 'DebugNode': 1}

    def test_stats_unknown_workflow_404(self, api_client):
        _create_wf(api_client, 'stats wf 2')
        resp = api_client.get('/api/workflow/stats?workflow=missing')
        assert resp.status_code == 404
