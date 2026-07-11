"""Import/export round-trip tests for WorkflowEngine.

Covers: export -> import -> export stability, unknown-node placeholder
behavior (disabled placeholder that round-trips back to its original
type/config), and system-error-node exclusion from exports.

Engines here use the real node registry (DebugNode, InjectNode, ErrorNode,
UnknownNode - all dependency-light). Engines are only started where the test
requires it, and every started engine is stopped in the fixture teardown.
"""

import pytest

from pynode.workflow_engine import WorkflowEngine
from pynode import nodes as node_pkg


def _make_engine():
    eng = WorkflowEngine()
    for cls in node_pkg.get_all_node_types():
        eng.register_node_type(cls)
    return eng


@pytest.fixture
def real_engine():
    eng = _make_engine()
    yield eng
    eng.stop()  # no-op unless a test started it


# ------------------------------------------------------------------
# export -> import -> export stability
# ------------------------------------------------------------------

class TestRoundTripStability:

    def _build_sample(self, engine):
        src = engine.create_node('InjectNode', 'rt-src', 'my source',
                                 {'topic': 'hello'})
        src.x, src.y = 10, 20
        mid = engine.create_node('ChangeNode', 'rt-mid', 'my change',
                                 {'rules': []})
        mid.x, mid.y = 30, 40
        dst = engine.create_node('DebugNode', 'rt-dst', 'my debug', {})
        dst.x, dst.y = 50, 60
        dst.enabled = False
        engine.connect_nodes('rt-src', 'rt-mid', 0, 0)
        engine.connect_nodes('rt-mid', 'rt-dst', 0, 0)

    def test_export_import_export_identical(self, real_engine):
        self._build_sample(real_engine)
        first = real_engine.export_workflow()

        second_engine = _make_engine()
        second_engine.import_workflow(first)
        second = second_engine.export_workflow()

        assert second == first

    def test_export_preserves_position_enabled_config(self, real_engine):
        self._build_sample(real_engine)
        exported = real_engine.export_workflow()

        by_id = {n['id']: n for n in exported['nodes']}
        assert by_id['rt-src']['x'] == 10 and by_id['rt-src']['y'] == 20
        assert by_id['rt-src']['config']['topic'] == 'hello'
        assert by_id['rt-src']['enabled'] is True
        assert by_id['rt-dst']['enabled'] is False
        assert by_id['rt-dst']['name'] == 'my debug'
        assert len(exported['connections']) == 2

    def test_import_is_deterministic_across_engines(self, real_engine):
        self._build_sample(real_engine)
        exported = real_engine.export_workflow()

        eng_a = _make_engine()
        eng_b = _make_engine()
        eng_a.import_workflow(exported)
        eng_b.import_workflow(exported)
        assert eng_a.export_workflow() == eng_b.export_workflow()


# ------------------------------------------------------------------
# Unknown node type placeholder
# ------------------------------------------------------------------

class TestUnknownNodePlaceholder:

    UNKNOWN_WORKFLOW = {
        'nodes': [
            {'id': 'ghost-1', 'type': 'TotallyFakeCameraNode',
             'name': 'my camera', 'config': {'device': 3, 'fps': 30},
             'enabled': True, 'x': 100, 'y': 200,
             'inputCount': 2, 'outputCount': 3},
            {'id': 'dbg-1', 'type': 'DebugNode', 'name': 'dbg',
             'config': {}, 'enabled': True, 'x': 0, 'y': 0},
        ],
        'connections': [
            {'source': 'ghost-1', 'target': 'dbg-1',
             'sourceOutput': 2, 'targetInput': 0},
        ],
    }

    def test_import_creates_disabled_placeholder(self, real_engine):
        real_engine.import_workflow(self.UNKNOWN_WORKFLOW)

        node = real_engine.get_node('ghost-1')
        assert node is not None
        assert node.type == 'UnknownNode'
        # The user-given name is preserved with a ' (missing)' marker
        assert node.name == 'my camera (missing)'
        assert node.enabled is False
        # Original port counts preserved so connections still fit
        assert node.input_count == 2
        assert node.output_count == 3
        assert node.config['original_type'] == 'TotallyFakeCameraNode'
        assert node.config['original_config'] == {'device': 3, 'fps': 30}
        # The connection from the placeholder's output 2 survived
        assert any(t.id == 'dbg-1'
                   for targets in node.outputs.values()
                   for t, _ in targets)

    def test_engine_still_functional_with_placeholder(self, real_engine):
        real_engine.import_workflow(self.UNKNOWN_WORKFLOW)
        extra = real_engine.create_node('InjectNode', 'extra-1', 'extra', {})
        real_engine.connect_nodes('extra-1', 'dbg-1', 0, 0)
        assert real_engine.get_node('extra-1') is extra
        stats = real_engine.get_workflow_stats()
        assert stats['total_nodes'] == 3

    def test_export_converts_placeholder_back_to_original(self, real_engine):
        real_engine.import_workflow(self.UNKNOWN_WORKFLOW)
        exported = real_engine.export_workflow()

        ghost = next(n for n in exported['nodes'] if n['id'] == 'ghost-1')
        assert ghost['type'] == 'TotallyFakeCameraNode'
        assert ghost['config'] == {'device': 3, 'fps': 30}
        assert ghost['enabled'] is False  # always exported disabled
        assert ghost['x'] == 100 and ghost['y'] == 200
        assert ghost['inputCount'] == 2
        assert ghost['outputCount'] == 3
        # The ' (missing)' suffix is stripped on export, so the original
        # user-given node name round-trips unchanged.
        assert ghost['name'] == 'my camera'
        # Connection from the placeholder is preserved in the export
        assert exported['connections'] == self.UNKNOWN_WORKFLOW['connections']

    def test_placeholder_without_name_falls_back_to_type(self, real_engine):
        real_engine.import_workflow({
            'nodes': [{'id': 'ghost-2', 'type': 'NamelessGhostNode',
                       'config': {}, 'enabled': True}],
            'connections': [],
        })
        node = real_engine.get_node('ghost-2')
        assert node.name == 'NamelessGhostNode (missing)'
        exported = real_engine.export_workflow()
        ghost = next(n for n in exported['nodes'] if n['id'] == 'ghost-2')
        assert ghost['name'] == 'NamelessGhostNode'

    def test_placeholder_round_trip_is_stable(self, real_engine):
        real_engine.import_workflow(self.UNKNOWN_WORKFLOW)
        first = real_engine.export_workflow()

        second_engine = _make_engine()
        second_engine.import_workflow(first)
        second = second_engine.export_workflow()
        assert second == first


# ------------------------------------------------------------------
# System error node exclusion
# ------------------------------------------------------------------

class TestSystemErrorNodeExclusion:

    def test_system_error_node_never_exported_while_running(self, real_engine):
        real_engine.create_node('InjectNode', 'sys-src', 'src', {})
        real_engine.start()

        assert '__system_error__' in real_engine.nodes  # created on start
        exported = real_engine.export_workflow()
        assert [n['id'] for n in exported['nodes']] == ['sys-src']

    def test_connections_to_system_error_node_excluded(self, real_engine):
        real_engine.create_node('InjectNode', 'sys-src', 'src', {})
        real_engine.start()
        real_engine.connect_nodes('sys-src', '__system_error__', 0, 0)

        exported = real_engine.export_workflow()
        assert exported['connections'] == []
        assert all(c['target'] != '__system_error__'
                   for c in exported['connections'])

    def test_import_while_running_recreates_system_error_node(self, real_engine):
        real_engine.create_node('DebugNode', 'old-node', 'old', {})
        real_engine.start()
        assert '__system_error__' in real_engine.nodes

        real_engine.import_workflow({
            'nodes': [{'id': 'new-node', 'type': 'DebugNode', 'name': 'new',
                       'config': {}, 'enabled': True}],
            'connections': [],
        })

        # Previous nodes cleared, new node present, system node recreated
        assert real_engine.get_node('old-node') is None
        assert real_engine.get_node('new-node') is not None
        assert '__system_error__' in real_engine.nodes
        assert real_engine.running is True

    def test_stats_exclude_system_error_node(self, real_engine):
        real_engine.create_node('InjectNode', 'sys-src', 'src', {})
        real_engine.start()
        assert '__system_error__' in real_engine.nodes
        real_engine.connect_nodes('sys-src', '__system_error__', 0, 0)

        stats = real_engine.get_workflow_stats()
        assert stats['total_nodes'] == 1
        assert stats['node_types'] == {'InjectNode': 1}
        # The connection into the system node is excluded too
        assert stats['total_connections'] == 0

    def test_import_while_stopped_does_not_create_system_node(self, real_engine):
        real_engine.import_workflow({
            'nodes': [{'id': 'n1', 'type': 'DebugNode', 'name': 'n',
                       'config': {}, 'enabled': True}],
            'connections': [],
        })
        assert '__system_error__' not in real_engine.nodes
