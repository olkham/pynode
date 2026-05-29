"""Tests for node and workflow serialization (to_dict, export/import)."""


def test_node_to_dict_contains_core_fields(engine):
    node = engine.create_node('_SourceNode', name='src', config={'foo': 'bar'})
    data = node.to_dict()

    assert data['id'] == node.id
    assert data['type'] == '_SourceNode'
    assert data['name'] == 'src'
    assert data['config']['foo'] == 'bar'
    assert data['enabled'] is True
    assert 'inputCount' in data
    assert 'outputCount' in data
    assert 'outputs' in data


def test_to_dict_serializes_connections(engine):
    src = engine.create_node('_SourceNode')
    sink = engine.create_node('_SinkNode')
    engine.connect_nodes(src.id, sink.id)

    data = src.to_dict()
    # outputs maps stringified output index -> list of [target_id, target_input]
    targets = [t for conns in data['outputs'].values() for t in conns]
    assert any(target_id == sink.id for target_id, _ in targets)


def test_export_workflow_structure(engine):
    src = engine.create_node('_SourceNode')
    sink = engine.create_node('_SinkNode')
    engine.connect_nodes(src.id, sink.id)

    exported = engine.export_workflow()
    assert 'nodes' in exported
    assert 'connections' in exported
    assert len(exported['nodes']) == 2
    assert len(exported['connections']) == 1

    conn = exported['connections'][0]
    assert conn['source'] == src.id
    assert conn['target'] == sink.id


def test_export_excludes_system_error_node(engine):
    engine.register_node_type(_make_dummy_error_node())
    engine.create_node('_SourceNode')
    engine.start()  # triggers creation of system error node

    exported = engine.export_workflow()
    exported_ids = [n['id'] for n in exported['nodes']]
    assert '__system_error__' not in exported_ids
    engine.stop()


def test_import_workflow_round_trip(engine):
    src = engine.create_node('_SourceNode', name='source-a')
    sink = engine.create_node('_SinkNode', name='sink-b')
    engine.connect_nodes(src.id, sink.id)
    exported = engine.export_workflow()

    # Import into a fresh engine that knows the same node types.
    from pynode.workflow_engine import WorkflowEngine
    from tests.conftest import _PassThroughNode, _SinkNode, _SourceNode

    new_engine = WorkflowEngine()
    for cls in (_SourceNode, _PassThroughNode, _SinkNode):
        new_engine.register_node_type(cls)

    new_engine.import_workflow(exported)

    re_exported = new_engine.export_workflow()
    assert len(re_exported['nodes']) == len(exported['nodes'])
    assert len(re_exported['connections']) == len(exported['connections'])

    names = {n['name'] for n in re_exported['nodes']}
    assert {'source-a', 'sink-b'} <= names


def test_import_unknown_node_creates_placeholder(engine):
    workflow_data = {
        'nodes': [
            {'id': 'ghost', 'type': 'TotallyMadeUpNode', 'name': 'ghost', 'config': {}}
        ],
        'connections': [],
    }
    engine.import_workflow(workflow_data)

    node = engine.get_node('ghost')
    assert node is not None
    # The placeholder preserves the original type when re-exported.
    exported = engine.export_workflow()
    assert exported['nodes'][0]['type'] == 'TotallyMadeUpNode'


def _make_dummy_error_node():
    """Build a minimal ErrorNode-compatible class for system-error tests."""
    from pynode.nodes.base_node import BaseNode

    class ErrorNode(BaseNode):
        input_count = 1
        output_count = 0

        def __init__(self, node_id=None, name=""):
            super().__init__(node_id=node_id, name=name)
            self._errors = []
            self.is_system_node = False

        def handle_error(self, source_id, source_name, error_msg):
            self._errors.append({'source': source_id, 'message': error_msg})

        def get_errors(self):
            return list(self._errors)

        def clear_errors(self):
            self._errors.clear()

    return ErrorNode
