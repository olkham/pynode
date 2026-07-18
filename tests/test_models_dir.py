"""Tests for the managed models / node-storage directory scheme.

Covers three pure/near-pure surfaces added to stop nodes scattering downloaded
binaries into the process CWD:

- ``pynode.config.resolve_models_dir`` precedence (a pure function of its
  args, tested without touching the real environment/filesystem),
- ``BaseNode.get_storage_dir`` (isolated by pointing PYNODE_DATA_DIR at
  ``tmp_path``; it only ever creates directories under that),
- ``pynode.nodes.UltralyticsNode.model_paths`` path resolution (exercised with
  tmp dirs and unique model names — no YOLO model is instantiated and nothing
  is downloaded).

Test-safety: no test touches the real data dir, workflows/, or downloads a
model. os.environ is only ever changed via monkeypatch, and every path written
lives under tmp_path.
"""

import os

from pynode import config
from pynode.config import resolve_models_dir
from pynode.nodes.base_node import BaseNode
from pynode.nodes.UltralyticsNode import model_paths


def _fake_checkout(tmp_path):
    """A directory that looks like a writable PyNode source checkout."""
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    (checkout / 'pyproject.toml').write_text('[project]\nname = "pynode"\n')
    return checkout


class TestResolveModelsDirPrecedence:

    def test_cli_flag_beats_env_and_default(self, tmp_path):
        cli_dir = tmp_path / 'cli-models'
        env_dir = tmp_path / 'env-models'
        data_dir = tmp_path / 'data'
        resolved = resolve_models_dir(
            cli_models_dir=str(cli_dir),
            environ={config.ENV_MODELS_DIR: str(env_dir),
                     config.ENV_DATA_DIR: str(data_dir)})
        assert resolved == os.path.abspath(str(cli_dir))

    def test_env_var_beats_data_dir_default(self, tmp_path):
        env_dir = tmp_path / 'env-models'
        data_dir = tmp_path / 'data'
        resolved = resolve_models_dir(
            environ={config.ENV_MODELS_DIR: str(env_dir),
                     config.ENV_DATA_DIR: str(data_dir)})
        assert resolved == os.path.abspath(str(env_dir))

    def test_default_is_models_subdir_of_data_dir(self, tmp_path):
        data_dir = tmp_path / 'data'
        resolved = resolve_models_dir(
            environ={config.ENV_DATA_DIR: str(data_dir)})
        assert resolved == os.path.join(os.path.abspath(str(data_dir)),
                                        config.MODELS_SUBDIR)

    def test_default_uses_source_checkout(self, tmp_path):
        # No overrides: models dir sits under the resolved data dir, which for
        # a source checkout is the checkout root -> <checkout>/models.
        checkout = _fake_checkout(tmp_path)
        resolved = resolve_models_dir(environ={}, checkout_dir=str(checkout))
        assert resolved == os.path.join(str(checkout), config.MODELS_SUBDIR)

    def test_empty_env_var_is_ignored(self, tmp_path):
        data_dir = tmp_path / 'data'
        resolved = resolve_models_dir(
            environ={config.ENV_MODELS_DIR: '',
                     config.ENV_DATA_DIR: str(data_dir)})
        assert resolved == os.path.join(os.path.abspath(str(data_dir)),
                                        config.MODELS_SUBDIR)

    def test_cli_flag_expands_user(self, tmp_path, monkeypatch):
        fake_home = tmp_path / 'home'

        def fake_expanduser(path):
            return path.replace('~', str(fake_home), 1)

        monkeypatch.setattr(config.os.path, 'expanduser', fake_expanduser)
        resolved = resolve_models_dir(cli_models_dir='~/pynode-models',
                                      environ={})
        assert resolved == os.path.abspath(
            os.path.join(str(fake_home), 'pynode-models'))

    def test_resolution_never_creates_dirs(self, tmp_path):
        data_dir = tmp_path / 'data'
        resolved = resolve_models_dir(
            environ={config.ENV_DATA_DIR: str(data_dir)})
        # resolve_* only resolves; creation happens at point of use.
        assert not os.path.exists(resolved)
        assert not data_dir.exists()


class _StorageProbeNode(BaseNode):
    """Trivial node subclass to assert get_storage_dir uses the node type."""


class TestGetStorageDir:

    def test_creates_and_returns_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
        node = BaseNode()
        path = node.get_storage_dir()
        expected = os.path.join(os.path.abspath(str(tmp_path)),
                                'node_storage', 'BaseNode')
        assert path == expected
        assert os.path.isdir(path)

    def test_subdir_appended_and_created(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
        node = BaseNode()
        path = node.get_storage_dir('weights')
        expected = os.path.join(os.path.abspath(str(tmp_path)),
                                'node_storage', 'BaseNode', 'weights')
        assert path == expected
        assert os.path.isdir(path)

    def test_uses_node_type_name(self, tmp_path, monkeypatch):
        monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path))
        node = _StorageProbeNode()
        path = node.get_storage_dir()
        assert path == os.path.join(os.path.abspath(str(tmp_path)),
                                    'node_storage', '_StorageProbeNode')
        assert os.path.isdir(path)


class TestResolveModelPath:
    # A name guaranteed not to collide with any real stray file in the repo
    # CWD (which _legacy_search_dirs includes).
    UNIQUE = 'pynode_test_unique_model_zzz.pt'

    def _legacy_dirs(self, tmp_path):
        """Fake checkout/pkg dirs so legacy lookups stay inside tmp_path."""
        checkout = tmp_path / 'checkout'
        pkg = tmp_path / 'pkg'
        (checkout / 'models').mkdir(parents=True)
        (pkg / 'models').mkdir(parents=True)
        (pkg / 'nodes').mkdir(parents=True)
        return checkout, pkg

    def test_absolute_path_passed_through(self, tmp_path):
        abs_path = str(tmp_path / 'custom' / 'weights.pt')
        assert model_paths.resolve_model_path(abs_path) == abs_path

    def test_relative_path_with_separator_passed_through(self):
        rel = 'subdir/my_model.pt'
        assert model_paths.resolve_model_path(rel) == rel

    def test_bare_name_found_in_models_dir(self, tmp_path):
        models_dir = tmp_path / 'models'
        models_dir.mkdir()
        weight = models_dir / self.UNIQUE
        weight.write_text('x')
        checkout, pkg = self._legacy_dirs(tmp_path)
        resolved = model_paths.resolve_model_path(
            self.UNIQUE, models_dir=str(models_dir),
            checkout_dir=str(checkout), pkg_dir=str(pkg))
        assert resolved == os.path.abspath(str(weight))

    def test_bare_name_found_in_legacy_dir(self, tmp_path):
        models_dir = tmp_path / 'models'
        models_dir.mkdir()  # empty -> not found here
        checkout, pkg = self._legacy_dirs(tmp_path)
        legacy_weight = checkout / 'models' / self.UNIQUE
        legacy_weight.write_text('x')
        resolved = model_paths.resolve_model_path(
            self.UNIQUE, models_dir=str(models_dir),
            checkout_dir=str(checkout), pkg_dir=str(pkg))
        assert resolved == os.path.abspath(str(legacy_weight))

    def test_bare_name_nowhere_returns_models_dir_and_creates_it(self, tmp_path):
        # models_dir does not exist yet -> must be created and the download
        # target path returned.
        models_dir = tmp_path / 'newmodels'
        checkout, pkg = self._legacy_dirs(tmp_path)
        resolved = model_paths.resolve_model_path(
            self.UNIQUE, models_dir=str(models_dir),
            checkout_dir=str(checkout), pkg_dir=str(pkg))
        assert resolved == os.path.join(str(models_dir), self.UNIQUE)
        assert os.path.isdir(str(models_dir))
        # Nothing was actually downloaded/created for the file itself.
        assert not os.path.exists(resolved)


class TestResolveOpenvinoExportDir:
    UNIQUE_STEM = 'pynode_test_unique_ovmodel_zzz'

    def _legacy_dirs(self, tmp_path):
        checkout = tmp_path / 'checkout'
        pkg = tmp_path / 'pkg'
        (checkout / 'models').mkdir(parents=True)
        (pkg / 'models').mkdir(parents=True)
        (pkg / 'nodes').mkdir(parents=True)
        return checkout, pkg

    def test_default_location_when_none_exists(self, tmp_path):
        source = str(tmp_path / 'models' / (self.UNIQUE_STEM + '.pt'))
        checkout, pkg = self._legacy_dirs(tmp_path)
        resolved = model_paths.resolve_openvino_export_dir(
            source, checkout_dir=str(checkout), pkg_dir=str(pkg))
        assert resolved == os.path.join(
            str(tmp_path / 'models'), self.UNIQUE_STEM + '_openvino_model')

    def test_existing_default_export_reused(self, tmp_path):
        models = tmp_path / 'models'
        models.mkdir()
        source = str(models / (self.UNIQUE_STEM + '.pt'))
        default_dir = models / (self.UNIQUE_STEM + '_openvino_model')
        default_dir.mkdir()
        checkout, pkg = self._legacy_dirs(tmp_path)
        resolved = model_paths.resolve_openvino_export_dir(
            source, checkout_dir=str(checkout), pkg_dir=str(pkg))
        assert resolved == str(default_dir)

    def test_existing_legacy_export_reused(self, tmp_path):
        # Source's default location does not exist, but a legacy export does.
        models = tmp_path / 'models'
        models.mkdir()
        source = str(models / (self.UNIQUE_STEM + '.pt'))
        checkout, pkg = self._legacy_dirs(tmp_path)
        legacy_export = checkout / 'models' / (self.UNIQUE_STEM
                                               + '_openvino_model')
        legacy_export.mkdir()
        resolved = model_paths.resolve_openvino_export_dir(
            source, checkout_dir=str(checkout), pkg_dir=str(pkg))
        assert resolved == os.path.abspath(str(legacy_export))
