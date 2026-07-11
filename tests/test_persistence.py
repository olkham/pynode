"""Tests for Phase 2.1: atomic workflow saves and backup pruning.

All disk I/O is sandboxed to tmp_path; the user's real workflows/ directory is
never touched. Because pynode.server keeps module-global workflow state, the
``isolated_workflow_state`` fixture snapshots and restores it around each test.
"""

import json
import os

import pytest

import pynode.server as server


@pytest.fixture
def tmp_paths(tmp_path, monkeypatch):
    """Point WORKFLOWS_DIR / WORKFLOW_FILE at a tmp directory."""
    workflows_dir = tmp_path / 'workflows'
    workflows_dir.mkdir()
    monkeypatch.setattr(server, 'WORKFLOWS_DIR', str(workflows_dir))
    monkeypatch.setattr(server, 'WORKFLOW_FILE', str(workflows_dir / 'workflow.json'))
    return workflows_dir


class TestSaveLoadRoundTrip:

    def test_round_trip(self, tmp_paths, isolated_workflow_state):
        wid = server._create_new_workflow(name='persist wf', workflow_id='wf_persist')
        node = server._working_engines[wid].create_node(
            'InjectNode', 'inj_1', 'my inject', {})
        node.x = 42
        node.y = 24

        server.save_workflow_to_disk()

        workflow_file = server.WORKFLOW_FILE
        assert os.path.isfile(workflow_file)

        # Wipe in-memory state and load back from disk
        with server._state_lock:
            server._workflows.clear()
            server._working_engines.clear()
            server._deployed_engines.clear()
            server._active_workflow_id = None

        server.load_workflow_from_disk()

        assert 'wf_persist' in server._workflows
        assert server._workflows['wf_persist']['name'] == 'persist wf'
        loaded = server._working_engines['wf_persist'].get_node('inj_1')
        assert loaded is not None
        assert loaded.name == 'my inject'
        assert loaded.x == 42
        assert loaded.y == 24
        assert server._active_workflow_id == 'wf_persist'

    def test_saved_file_is_valid_json_v2(self, tmp_paths, isolated_workflow_state):
        server._create_new_workflow(name='json wf', workflow_id='wf_json')
        server.save_workflow_to_disk()

        with open(server.WORKFLOW_FILE) as f:
            data = json.load(f)
        assert data['version'] == 2
        assert data['activeWorkflow'] == 'wf_json'
        assert [w['id'] for w in data['workflows']] == ['wf_json']

    def test_no_tmp_file_remains_after_save(self, tmp_paths, isolated_workflow_state):
        server._create_new_workflow(name='atomic wf')
        server.save_workflow_to_disk()
        # Save again so the atomic-replace path runs with an existing target
        server.save_workflow_to_disk()

        assert os.path.isfile(server.WORKFLOW_FILE)
        assert not os.path.exists(server.WORKFLOW_FILE + '.tmp')
        leftovers = [f for f in os.listdir(server.WORKFLOWS_DIR)
                     if f.endswith('.tmp')]
        assert leftovers == []


class TestBackupPruning:

    def test_prunes_to_max_backups_keeping_newest(self, tmp_paths, isolated_workflow_state):
        server._create_new_workflow(name='backup wf')
        # First save creates workflow.json (no backup yet: file didn't exist)
        server.save_workflow_to_disk()

        backup_dir = os.path.join(server.WORKFLOWS_DIR, '_backups')
        os.makedirs(backup_dir, exist_ok=True)

        # Pre-create more than MAX_BACKUPS fake old backups. Their timestamps
        # sort lexically before any real backup created "now".
        fake_names = [f'workflow_20200101_{i:06d}.json' for i in range(25)]
        for name in fake_names:
            with open(os.path.join(backup_dir, name), 'w') as f:
                f.write('{}')

        # This save backs up the existing workflow.json, then prunes
        server.save_workflow_to_disk()

        remaining = sorted(
            f for f in os.listdir(backup_dir)
            if f.startswith('workflow_') and f.endswith('.json')
        )
        assert len(remaining) == server.MAX_BACKUPS

        # The newest files must have been kept: all survivors sort >= the
        # newest pruned name, and the just-created backup (newest of all,
        # timestamp 2026+) is among them.
        all_names = sorted(set(fake_names) | set(remaining))
        assert remaining == all_names[-server.MAX_BACKUPS:]
        assert remaining[-1] not in fake_names  # newest is the real backup

    def test_backup_created_on_save_over_existing_file(self, tmp_paths, isolated_workflow_state):
        server._create_new_workflow(name='backup wf 2')
        server.save_workflow_to_disk()
        server.save_workflow_to_disk()

        backup_dir = os.path.join(server.WORKFLOWS_DIR, '_backups')
        backups = [f for f in os.listdir(backup_dir)
                   if f.startswith('workflow_') and f.endswith('.json')]
        assert len(backups) >= 1
