"""Central configuration for PyNode.

Consolidates the environment variables and path-resolution conventions that
were previously scattered across ``main.py``, ``server.py`` and
``workflow_manager.py``.

Environment variables
---------------------

- ``PYNODE_DATA_DIR``: directory that holds PyNode's mutable data. Workflows
  are persisted under ``<data dir>/workflows/`` (``workflow.json`` plus the
  ``_backups/`` folder). Overridden by the ``--data-dir`` CLI flag. See
  :func:`resolve_data_dir` for the full precedence.
- ``PYNODE_MODELS_DIR``: directory for shared model weights (e.g. YOLO
  ``.pt`` files and exported OpenVINO models). Nodes must download/read model
  binaries here instead of scattering them into the process CWD. Defaults to
  ``<data dir>/models``. Overridden by the ``--models-dir`` CLI flag. See
  :func:`resolve_models_dir` for the full precedence.
- ``PYNODE_API_KEY``: API key required on all ``/api/`` requests
  (``X-API-Key`` header or ``api_key`` query parameter). Empty/unset = auth
  disabled. Overridden by the ``--api-key`` CLI flag.
- ``PYNODE_CORS_ORIGINS``: comma-separated list of allowed CORS origins.
  Empty/unset = ``*`` (all origins). Overridden by the ``--cors-origins``
  CLI flag.
"""

import os

# Environment variable names (single source of truth).
ENV_DATA_DIR = 'PYNODE_DATA_DIR'
ENV_MODELS_DIR = 'PYNODE_MODELS_DIR'
ENV_API_KEY = 'PYNODE_API_KEY'
ENV_CORS_ORIGINS = 'PYNODE_CORS_ORIGINS'

# Package directory (static files, package-relative uploads).
PKG_DIR = os.path.dirname(os.path.abspath(__file__))

# Directory the ``pynode`` package sits in. For a source checkout this is the
# repository root (which contains pyproject.toml and workflows/); for a pip
# install it is site-packages, which must NOT be used as a data directory.
CHECKOUT_DIR = os.path.dirname(PKG_DIR)

# Name of the workflows subdirectory inside the data dir.
WORKFLOWS_SUBDIR = 'workflows'

# Name of the models subdirectory inside the data dir (shared model weights).
MODELS_SUBDIR = 'models'


def _is_source_checkout(base_dir):
    """True if ``base_dir`` looks like a writable PyNode source checkout.

    Heuristic: ``pyproject.toml`` sits next to the ``pynode`` package (true
    for a git clone / editable install, false for site-packages) and the
    directory is writable.
    """
    try:
        return (os.path.isfile(os.path.join(base_dir, 'pyproject.toml'))
                and os.path.isdir(base_dir)
                and os.access(base_dir, os.W_OK))
    except OSError:
        return False


def resolve_data_dir(cli_data_dir=None, environ=None, checkout_dir=None):
    """Resolve the PyNode data directory (parent of ``workflows/``).

    Precedence:

    1. ``cli_data_dir`` (the ``--data-dir`` CLI flag),
    2. the ``PYNODE_DATA_DIR`` environment variable,
    3. the source-checkout root (directory containing the ``pynode``
       package) IF it looks like a writable source checkout — i.e.
       ``pyproject.toml`` is present next to the package,
    4. otherwise ``~/.pynode`` (the pip-installed case, where the package
       parent would be site-packages).

    The directory is only resolved here, never created — creation happens in
    ``WorkflowManager`` when the app is built.
    """
    environ = os.environ if environ is None else environ
    checkout_dir = CHECKOUT_DIR if checkout_dir is None else checkout_dir

    if cli_data_dir:
        return os.path.abspath(os.path.expanduser(cli_data_dir))

    env_dir = environ.get(ENV_DATA_DIR)
    if env_dir:
        return os.path.abspath(os.path.expanduser(env_dir))

    if _is_source_checkout(checkout_dir):
        return checkout_dir

    return os.path.join(os.path.expanduser('~'), '.pynode')


def resolve_workflows_dir(cli_data_dir=None, environ=None, checkout_dir=None):
    """The workflows directory inside the resolved data dir."""
    return os.path.join(
        resolve_data_dir(cli_data_dir=cli_data_dir, environ=environ,
                         checkout_dir=checkout_dir),
        WORKFLOWS_SUBDIR)


def resolve_models_dir(cli_models_dir=None, environ=None, checkout_dir=None):
    """Resolve the shared models directory for downloaded model weights.

    Nodes that download or generate model binaries (YOLO ``.pt`` files,
    exported OpenVINO models, etc.) must place them here rather than in the
    process CWD, so a pip-installed PyNode launched from a read-only or
    arbitrary directory does not scatter files around.

    Precedence:

    1. ``cli_models_dir`` (the ``--models-dir`` CLI flag),
    2. the ``PYNODE_MODELS_DIR`` environment variable,
    3. ``<resolve_data_dir(...)>/models`` (the ``models`` subdirectory of the
       resolved data dir — for a source checkout this is ``<repo>/models``,
       for a pip install ``~/.pynode/models``).

    Like :func:`resolve_data_dir`, the directory is only resolved here, never
    created — creation happens lazily at the point of use.
    """
    environ = os.environ if environ is None else environ

    if cli_models_dir:
        return os.path.abspath(os.path.expanduser(cli_models_dir))

    env_dir = environ.get(ENV_MODELS_DIR)
    if env_dir:
        return os.path.abspath(os.path.expanduser(env_dir))

    return os.path.join(
        resolve_data_dir(environ=environ, checkout_dir=checkout_dir),
        MODELS_SUBDIR)
