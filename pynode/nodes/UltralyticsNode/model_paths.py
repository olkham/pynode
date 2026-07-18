"""Path resolution for Ultralytics YOLO weights and OpenVINO exports.

Deliberately free of heavy imports (no ``torch`` / ``ultralytics``) so the pure
path logic is unit-testable in isolation and importable in a core-only install.

Project storage rule (see :meth:`pynode.nodes.base_node.BaseNode.get_storage_dir`
and :func:`pynode.config.resolve_models_dir`): model binaries live in the shared
models dir, never the process CWD. Older PyNode versions scattered ``.pt`` files
and ``*_openvino_model/`` folders into whatever the CWD happened to be, so the
resolvers below also look in a handful of legacy locations for read-only reuse —
nothing found there is ever moved or deleted (that dir may hold real user
models).
"""

import os

from pynode import config


def _has_path_separator(name: str) -> bool:
    """True if ``name`` is an absolute path or contains a path separator.

    Such values are treated as user-specified paths and used verbatim; a bare
    filename (e.g. ``yolo26n.pt``) is subject to models-dir resolution.
    """
    if os.path.isabs(name):
        return True
    seps = {os.sep, '/'}
    if os.altsep:
        seps.add(os.altsep)
    return any(sep in name for sep in seps)


def _legacy_search_dirs(checkout_dir=None, pkg_dir=None):
    """Legacy locations older versions may have scattered model files into.

    Order: process CWD, the repo checkout root, ``<checkout>/models``,
    ``<pkg>/models`` and ``<pkg>/nodes``. Read-only reuse only.
    """
    checkout_dir = config.CHECKOUT_DIR if checkout_dir is None else checkout_dir
    pkg_dir = config.PKG_DIR if pkg_dir is None else pkg_dir
    return [
        os.getcwd(),
        checkout_dir,
        os.path.join(checkout_dir, 'models'),
        os.path.join(pkg_dir, 'models'),
        os.path.join(pkg_dir, 'nodes'),
    ]


def resolve_model_path(model_name, models_dir=None, environ=None,
                       checkout_dir=None, pkg_dir=None):
    """Resolve a configured YOLO ``model`` value to an absolute path.

    Behavior:

    a. An absolute path or any value containing a path separator is a
       user-specified path and is returned unchanged (never relocated).
    b. A bare filename (e.g. ``yolo26n.pt``) is looked up first in the shared
       models dir, then in the legacy locations. The first existing file found
       is returned as an absolute path (read-only reuse; nothing is moved).
    c. If not found anywhere, ``<models_dir>/<name>`` is returned as an
       absolute path and the models dir is created (``exist_ok=True``) so
       Ultralytics downloads the known asset there instead of into the CWD.

    Args:
        model_name: The configured ``model`` value.
        models_dir: Override the shared models dir (defaults to
            :func:`pynode.config.resolve_models_dir`); mainly for tests.
        environ / checkout_dir / pkg_dir: Overrides threaded through to
            resolution helpers; mainly for tests.
    """
    if _has_path_separator(model_name):
        return model_name

    if models_dir is None:
        models_dir = config.resolve_models_dir(environ=environ,
                                                checkout_dir=checkout_dir)

    search_dirs = [models_dir] + _legacy_search_dirs(
        checkout_dir=checkout_dir, pkg_dir=pkg_dir)
    for directory in search_dirs:
        candidate = os.path.join(directory, model_name)
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)

    os.makedirs(models_dir, exist_ok=True)
    return os.path.join(models_dir, model_name)


def resolve_openvino_export_dir(source_path, checkout_dir=None, pkg_dir=None):
    """Resolve the OpenVINO export directory for a resolved ``.pt`` path.

    The default export location is ``<source_stem>_openvino_model`` next to
    ``source_path`` (for a models-dir model that is inside the models dir,
    where Ultralytics' ``export(format='openvino')`` writes it automatically).

    Returns an already-existing export directory when one is found — first the
    default location, then the same legacy locations used for weights — so a
    previously exported model is reused instead of re-exported. If none exists,
    the default location is returned for the caller to export into.
    """
    default_dir = os.path.splitext(source_path)[0] + '_openvino_model'
    if os.path.isdir(default_dir):
        return default_dir

    export_name = (os.path.splitext(os.path.basename(source_path))[0]
                   + '_openvino_model')
    for directory in _legacy_search_dirs(checkout_dir=checkout_dir,
                                         pkg_dir=pkg_dir):
        candidate = os.path.join(directory, export_name)
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)

    return default_dir
