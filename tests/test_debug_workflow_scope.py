"""Debug messages must carry the workflow (flow tab) id they originated
from, so the frontend debug panel can scope its list to the active flow.

Uses the sandboxed ``api_client``/``manager`` fixtures from conftest.py -
fresh tmp-path app per test, no disk writes to the real workflows/ dir, and
no worker threads are started (DebugNode.on_input and consume_messages are
called directly rather than running a live engine or SSE stream), so there
is nothing for the teardown to leak.
"""

import pytest


def _create_workflow(client, name):
    resp = client.post('/api/workflows', json={'name': name})
    assert resp.status_code == 201
    return resp.get_json()['id']


def _create_debug_node(client, workflow_id):
    resp = client.post(f'/api/nodes?workflow={workflow_id}',
                        json={'type': 'DebugNode', 'name': 'dbg'})
    assert resp.status_code == 201
    return resp.get_json()['id']


class TestDebugMessageWorkflowScope:

    def test_engine_carries_workflow_id(self, api_client):
        """WorkflowManager tags both engines it creates with the owning
        workflow id (the mechanism DebugNode relies on to tag messages)."""
        wid = _create_workflow(api_client, 'wf-engine-id')
        manager = api_client.manager
        assert manager.working_engines[wid].workflow_id == wid
        assert manager.deployed_engines[wid].workflow_id == wid

    def test_rest_debug_endpoint_includes_workflow_id(self, api_client):
        """GET /api/nodes/<id>/debug entries are tagged with the workflow
        the DebugNode instance belongs to."""
        wid = _create_workflow(api_client, 'wf-rest')
        node_id = _create_debug_node(api_client, wid)

        # Deploy so the node exists in the deployed engine (REST /debug
        # resolves handlers against deployed nodes, see _find_deployed_node).
        assert api_client.post('/api/workflow/save').status_code == 200

        deployed_node = api_client.manager.deployed_engines[wid].get_node(node_id)
        deployed_node.on_input({'payload': 'hello from wf-rest'})

        resp = api_client.get(f'/api/nodes/{node_id}/debug')
        assert resp.status_code == 200
        messages = resp.get_json()
        assert len(messages) == 1
        assert messages[0]['workflowId'] == wid
        assert messages[0]['output'] == 'hello from wf-rest'

    def test_two_workflows_tag_messages_distinctly(self, api_client):
        """Messages from two different flows carry their own, distinct
        workflow ids - proving the tag isn't a hardcoded/shared value."""
        wid_a = _create_workflow(api_client, 'wf-a')
        node_a = _create_debug_node(api_client, wid_a)
        wid_b = _create_workflow(api_client, 'wf-b')
        node_b = _create_debug_node(api_client, wid_b)

        assert api_client.post('/api/workflow/save').status_code == 200

        api_client.manager.deployed_engines[wid_a].get_node(node_a).on_input(
            {'payload': 'from a'})
        api_client.manager.deployed_engines[wid_b].get_node(node_b).on_input(
            {'payload': 'from b'})

        msgs_a = api_client.get(f'/api/nodes/{node_a}/debug').get_json()
        msgs_b = api_client.get(f'/api/nodes/{node_b}/debug').get_json()

        assert msgs_a[0]['workflowId'] == wid_a
        assert msgs_b[0]['workflowId'] == wid_b
        assert wid_a != wid_b

    def test_sse_consume_messages_payload_includes_workflow_id(self, api_client):
        """``consume_messages`` is the exact handler the SSE broadcast worker
        calls for DebugNode (see WorkflowManager._debug_broadcast_worker,
        which wraps its result as {'type': 'messages', 'data': result,
        'workflowId': wid}). Assert the per-message payload it returns is
        already tagged, independent of the broadcast thread/transport."""
        wid = _create_workflow(api_client, 'wf-sse')
        node_id = _create_debug_node(api_client, wid)
        assert api_client.post('/api/workflow/save').status_code == 200

        deployed_node = api_client.manager.deployed_engines[wid].get_node(node_id)
        deployed_node.on_input({'payload': 'sse payload'})

        result = deployed_node.consume_messages()
        assert result is not None
        assert len(result) == 1
        assert result[0]['workflowId'] == wid

        # consume_messages() also drains the buffer (matches the broadcast
        # worker's expectation that each message is sent once).
        assert deployed_node.consume_messages() is None

    def test_message_without_workflow_engine_has_none_workflow_id(self):
        """A DebugNode with no workflow engine attached (e.g. constructed
        directly, as in unit tests) yields workflowId=None rather than
        raising - the frontend treats this as backward-compat / no flow."""
        from pynode.nodes.DebugNode.debug_node import DebugNode

        node = DebugNode(node_id='standalone', name='standalone')
        node.on_input({'payload': 'no engine'})
        assert node.messages[0]['workflowId'] is None


class TestDebugPanelFlowSelectorMarkup:

    def test_served_index_html_has_flow_scope_selector(self, api_client):
        """The debug panel header must expose the 'Current flow'/'All
        flows' selector so the served frontend can be wired up to it."""
        resp = api_client.get('/')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'id="debug-flow-filter"' in html
        assert 'Current flow' in html
        assert 'All flows' in html
