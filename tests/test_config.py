"""Tests for pynode.config data-directory resolution.

resolve_data_dir() is a pure function of its parameters (cli flag, environ
mapping, checkout dir), so precedence is tested without touching the real
environment or filesystem locations. The home-dir fallback is exercised with
a monkeypatched expanduser so ~/.pynode is never created or referenced for
real (resolve_data_dir never creates directories anyway).
"""

import os

from pynode import config
from pynode.config import resolve_data_dir, resolve_workflows_dir


def _fake_checkout(tmp_path):
    """A directory that looks like a PyNode source checkout."""
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    (checkout / 'pyproject.toml').write_text('[project]\nname = "pynode"\n')
    return checkout


def _fake_site_packages(tmp_path):
    """A directory that looks like site-packages (no pyproject.toml)."""
    site = tmp_path / 'site-packages'
    site.mkdir()
    return site


class TestResolveDataDirPrecedence:

    def test_cli_flag_beats_env_var(self, tmp_path):
        cli_dir = tmp_path / 'cli-data'
        env_dir = tmp_path / 'env-data'
        resolved = resolve_data_dir(
            cli_data_dir=str(cli_dir),
            environ={config.ENV_DATA_DIR: str(env_dir)},
            checkout_dir=str(_fake_checkout(tmp_path)))
        assert resolved == os.path.abspath(str(cli_dir))

    def test_env_var_beats_checkout_default(self, tmp_path):
        env_dir = tmp_path / 'env-data'
        resolved = resolve_data_dir(
            environ={config.ENV_DATA_DIR: str(env_dir)},
            checkout_dir=str(_fake_checkout(tmp_path)))
        assert resolved == os.path.abspath(str(env_dir))

    def test_source_checkout_used_when_no_overrides(self, tmp_path):
        checkout = _fake_checkout(tmp_path)
        resolved = resolve_data_dir(environ={}, checkout_dir=str(checkout))
        assert resolved == str(checkout)

    def test_non_checkout_falls_back_to_home_pynode(self, tmp_path, monkeypatch):
        # Fake a pip-installed layout: the package parent has no
        # pyproject.toml, so resolution must NOT use it (it would be
        # site-packages) and must fall back to ~/.pynode.
        fake_home = tmp_path / 'home'

        def fake_expanduser(path):
            return path.replace('~', str(fake_home), 1)

        monkeypatch.setattr(config.os.path, 'expanduser', fake_expanduser)
        resolved = resolve_data_dir(
            environ={}, checkout_dir=str(_fake_site_packages(tmp_path)))
        assert resolved == os.path.join(str(fake_home), '.pynode')
        # Only resolved, never created.
        assert not fake_home.exists()

    def test_empty_env_var_is_ignored(self, tmp_path):
        checkout = _fake_checkout(tmp_path)
        resolved = resolve_data_dir(
            environ={config.ENV_DATA_DIR: ''}, checkout_dir=str(checkout))
        assert resolved == str(checkout)

    def test_cli_flag_expands_user(self, tmp_path, monkeypatch):
        fake_home = tmp_path / 'home'

        def fake_expanduser(path):
            return path.replace('~', str(fake_home), 1)

        monkeypatch.setattr(config.os.path, 'expanduser', fake_expanduser)
        resolved = resolve_data_dir(cli_data_dir='~/pynode-data', environ={})
        assert resolved == os.path.abspath(os.path.join(str(fake_home),
                                                        'pynode-data'))


class TestResolveWorkflowsDir:

    def test_workflows_subdir_of_data_dir(self, tmp_path):
        env_dir = tmp_path / 'data'
        resolved = resolve_workflows_dir(
            environ={config.ENV_DATA_DIR: str(env_dir)})
        assert resolved == os.path.join(os.path.abspath(str(env_dir)),
                                        'workflows')

    def test_this_repo_resolves_to_repo_workflows_dir(self):
        # The dev setup (source checkout with pyproject.toml) must keep
        # resolving to <repo>/workflows with no flags or env vars set.
        resolved = resolve_workflows_dir(environ={})
        assert resolved == os.path.join(config.CHECKOUT_DIR, 'workflows')
        assert os.path.isfile(os.path.join(config.CHECKOUT_DIR,
                                           'pyproject.toml'))


class TestCreateAppDataDir:

    def test_create_app_data_dir_config_key(self, tmp_path):
        """create_app({'DATA_DIR': ...}) persists workflows under it."""
        from pynode.server import create_app

        data_dir = tmp_path / 'appdata'
        app = create_app({'DATA_DIR': str(data_dir), 'TESTING': True})
        manager = app.extensions['workflow_manager']
        try:
            expected = os.path.join(os.path.abspath(str(data_dir)),
                                    'workflows')
            assert manager.workflows_dir == expected
            assert manager.workflow_file == os.path.join(expected,
                                                         'workflow.json')
            assert os.path.isdir(expected)
        finally:
            manager.shutdown()

    def test_explicit_workflows_dir_beats_data_dir(self, tmp_path):
        from pynode.server import create_app

        app = create_app({
            'DATA_DIR': str(tmp_path / 'ignored'),
            'WORKFLOWS_DIR': str(tmp_path / 'explicit'),
            'TESTING': True,
        })
        manager = app.extensions['workflow_manager']
        try:
            assert manager.workflows_dir == str(tmp_path / 'explicit')
        finally:
            manager.shutdown()
