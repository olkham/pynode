"""Tests for Phase 2.1: atomic workflow saves and backup pruning.

All disk I/O is sandboxed to tmp_path; the user's real workflows/ directory is
never touched. Each test gets its own ``WorkflowManager`` instance pointed at
tmp_path, so no state is shared between tests (or with any Flask app).
"""

import json
import os

import pytest

from pynode.workflow_manager import WorkflowManager


@pytest.fixture
def mgr(tmp_path):
    """A WorkflowManager whose persistence paths live under tmp_path."""
    workflows_dir = tmp_path / 'workflows'
    manager = WorkflowManager(
        workflows_dir=str(workflows_dir),
        workflow_file=str(workflows_dir / 'workflow.json'),
    )
    yield manager
    # Stop any engines (and their worker threads) the test started
    manager.shutdown()


class TestSaveLoadRoundTrip:

    def test_round_trip(self, mgr):
        wid = mgr.create_new_workflow(name='persist wf', workflow_id='wf_persist')
        node = mgr.working_engines[wid].create_node(
            'InjectNode', 'inj_1', 'my inject', {})
        node.x = 42
        node.y = 24

        mgr.save_workflow_to_disk()

        workflow_file = mgr.workflow_file
        assert os.path.isfile(workflow_file)

        # Wipe in-memory state and load back from disk
        with mgr.state_lock:
            mgr.workflows.clear()
            mgr.working_engines.clear()
            mgr.deployed_engines.clear()
            mgr.active_workflow_id = None

        mgr.load_workflow_from_disk()

        assert 'wf_persist' in mgr.workflows
        assert mgr.workflows['wf_persist']['name'] == 'persist wf'
        loaded = mgr.working_engines['wf_persist'].get_node('inj_1')
        assert loaded is not None
        assert loaded.name == 'my inject'
        assert loaded.x == 42
        assert loaded.y == 24
        assert mgr.active_workflow_id == 'wf_persist'

    def test_saved_file_is_valid_json_v2(self, mgr):
        mgr.create_new_workflow(name='json wf', workflow_id='wf_json')
        mgr.save_workflow_to_disk()

        with open(mgr.workflow_file) as f:
            data = json.load(f)
        assert data['version'] == 2
        assert data['activeWorkflow'] == 'wf_json'
        assert [w['id'] for w in data['workflows']] == ['wf_json']

    def test_no_tmp_file_remains_after_save(self, mgr):
        mgr.create_new_workflow(name='atomic wf')
        mgr.save_workflow_to_disk()
        # Save again so the atomic-replace path runs with an existing target
        mgr.save_workflow_to_disk()

        assert os.path.isfile(mgr.workflow_file)
        assert not os.path.exists(mgr.workflow_file + '.tmp')
        leftovers = [f for f in os.listdir(mgr.workflows_dir)
                     if f.endswith('.tmp')]
        assert leftovers == []


class TestBackupPruning:

    def test_prunes_to_max_backups_keeping_newest(self, mgr):
        mgr.create_new_workflow(name='backup wf')
        # First save creates workflow.json (no backup yet: file didn't exist)
        mgr.save_workflow_to_disk()

        backup_dir = os.path.join(mgr.workflows_dir, '_backups')
        os.makedirs(backup_dir, exist_ok=True)

        # Pre-create more than max_backups fake old backups. Their timestamps
        # sort lexically before any real backup created "now".
        fake_names = [f'workflow_20200101_{i:06d}.json' for i in range(25)]
        for name in fake_names:
            with open(os.path.join(backup_dir, name), 'w') as f:
                f.write('{}')

        # This save backs up the existing workflow.json, then prunes
        mgr.save_workflow_to_disk()

        remaining = sorted(
            f for f in os.listdir(backup_dir)
            if f.startswith('workflow_') and f.endswith('.json')
        )
        assert len(remaining) == mgr.max_backups

        # The newest files must have been kept: all survivors sort >= the
        # newest pruned name, and the just-created backup (newest of all,
        # timestamp 2026+) is among them.
        all_names = sorted(set(fake_names) | set(remaining))
        assert remaining == all_names[-mgr.max_backups:]
        assert remaining[-1] not in fake_names  # newest is the real backup

    def test_backup_created_on_save_over_existing_file(self, mgr):
        mgr.create_new_workflow(name='backup wf 2')
        mgr.save_workflow_to_disk()
        mgr.save_workflow_to_disk()

        backup_dir = os.path.join(mgr.workflows_dir, '_backups')
        backups = [f for f in os.listdir(backup_dir)
                   if f.startswith('workflow_') and f.endswith('.json')]
        assert len(backups) >= 1
