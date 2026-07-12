"""
Flask app factory for the Node-RED-like system.

``create_app()`` builds a Flask app with its own ``WorkflowManager``
(``app.extensions['workflow_manager']``), CORS, optional API-key auth, JSON
error handlers and all API blueprints (see ``pynode.api``). A module-level
default instance (``app``) is kept for backwards compatibility so
``from pynode.server import app`` keeps working (pynode.main, user code).

Route implementations live in the ``pynode.api`` blueprints; the mutable
workflow state lives in ``pynode.workflow_manager``; static node-type
registries live in ``pynode.node_registry``.
"""

import hmac
import logging
import os

from flask import Flask, request, send_from_directory
from flask_cors import CORS

from pynode.config import resolve_workflows_dir
from pynode.api import register_blueprints
from pynode.api.helpers import _json_error
from pynode.api.uploads import ALLOWED_UPLOAD_SUBDIRS  # noqa: F401 (re-export)
from pynode.workflow_manager import BASE_DIR, MAX_BACKUPS, PKG_DIR, WorkflowManager

logger = logging.getLogger(__name__)


def _parse_cors_origins(value):
    """Parse a comma-separated origins string into a flask-cors ``origins`` arg.

    ``None``, empty/blank strings, or any list containing ``*`` mean "all
    origins" (today's default behavior). Otherwise returns the list of
    origins with whitespace stripped.
    """
    if value is None:
        return '*'
    origins = [o.strip() for o in value.split(',') if o.strip()]
    if not origins or '*' in origins:
        return '*'
    return origins


def create_app(config=None):
    """Create and configure a PyNode Flask app.

    ``config`` may contain:

    - ``CORS_ORIGINS``: comma-separated allowed origins (default: the
      PYNODE_CORS_ORIGINS env var, else ``*``).
    - ``PYNODE_API_KEY``: API key required on /api/ requests (default: the
      PYNODE_API_KEY env var, else '' = auth disabled).
    - ``DATA_DIR``: PyNode data directory; workflows are persisted under
      ``<DATA_DIR>/workflows/`` (default: ``pynode.config.resolve_data_dir()``,
      which honors the PYNODE_DATA_DIR env var).
    - ``WORKFLOWS_DIR`` / ``WORKFLOW_FILE`` / ``UPLOAD_BASE_DIR``: persistence
      and upload paths for this app's WorkflowManager (override ``DATA_DIR``).

    Any remaining keys are applied to ``app.config`` (e.g. ``TESTING``).
    """
    cfg = dict(config or {})

    app = Flask(__name__, static_folder=os.path.join(PKG_DIR, 'static'),
                static_url_path='')

    # Enable CORS for the frontend. Origins are configurable via config or
    # the PYNODE_CORS_ORIGINS env var (comma-separated); default is open
    # ('*'), matching the original CORS(app) behavior.
    cors_origins = cfg.pop('CORS_ORIGINS', os.environ.get('PYNODE_CORS_ORIGINS'))
    CORS(app, origins=_parse_cors_origins(cors_origins))

    # Optional API key authentication (see _require_api_key below).
    app.config['PYNODE_API_KEY'] = cfg.pop(
        'PYNODE_API_KEY', os.environ.get('PYNODE_API_KEY', ''))

    # Per-app workflow state / persistence / SSE broadcast owner. Explicit
    # WORKFLOWS_DIR wins; otherwise the workflows dir is derived from
    # DATA_DIR (or, when neither is given, from pynode.config resolution:
    # PYNODE_DATA_DIR env var > source checkout root > ~/.pynode).
    data_dir = cfg.pop('DATA_DIR', None)
    workflows_dir = cfg.pop('WORKFLOWS_DIR', None)
    if workflows_dir is None:
        workflows_dir = resolve_workflows_dir(cli_data_dir=data_dir)
    manager = WorkflowManager(
        workflows_dir=workflows_dir,
        workflow_file=cfg.pop('WORKFLOW_FILE', None),
        upload_base_dir=cfg.pop('UPLOAD_BASE_DIR', None),
    )
    app.extensions['workflow_manager'] = manager
    logger.info(f"Workflow data directory: {manager.workflows_dir}")

    # Remaining config keys (e.g. TESTING) go straight to app.config.
    app.config.update(cfg)

    # ------------------------------------------------------------------
    # Optional API key authentication.
    # When app.config['PYNODE_API_KEY'] is a non-empty string, every /api/
    # request must present the key via the X-API-Key header or the api_key
    # query parameter (the latter exists for EventSource, which cannot set
    # headers). Static assets and the index page stay open so the UI can load
    # and prompt the user for the key. Empty/unset key = auth disabled
    # (default behavior).
    # ------------------------------------------------------------------

    @app.before_request
    def _require_api_key():
        # Read dynamically from app.config (not captured at creation) so tests
        # and pynode.main can set/clear the key at runtime.
        key = app.config.get('PYNODE_API_KEY') or ''
        if not key:
            return None  # Auth disabled
        if request.method == 'OPTIONS':
            return None  # CORS preflight requests cannot carry custom headers
        if not request.path.startswith('/api/'):
            return None  # Static assets / index stay open
        provided = request.headers.get('X-API-Key') or request.args.get('api_key') or ''
        if not hmac.compare_digest(provided, key):
            return _json_error('Invalid or missing API key', 401)
        return None

    # ------------------------------------------------------------------
    # JSON error envelopes: API clients always get JSON, never Flask's HTML
    # error pages. Error contract: {'success': False, 'error': str}.
    # ------------------------------------------------------------------

    @app.errorhandler(400)
    def _handle_400(e):
        return _json_error(getattr(e, 'description', None) or 'Bad request', 400)

    @app.errorhandler(404)
    def _handle_404(e):
        return _json_error('Not found', 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return _json_error('Method not allowed', 405)

    @app.errorhandler(500)
    def _handle_500(e):
        return _json_error('Internal server error', 500)

    @app.route('/')
    def index():
        """Serve the main UI."""
        return send_from_directory(os.path.join(PKG_DIR, 'static'), 'index.html')

    register_blueprints(app)

    return app


# ----------------------------------------------------------------------
# Backwards-compatible module-level default instance.
# ``from pynode.server import app`` (pynode.main, user code) keeps working;
# the module-level functions below operate on this default app's manager.
# ----------------------------------------------------------------------

app = create_app()

_default_manager = app.extensions['workflow_manager']

# Informational re-exports describing the default instance's paths.
WORKFLOWS_DIR = _default_manager.workflows_dir
WORKFLOW_FILE = _default_manager.workflow_file
UPLOAD_BASE_DIR = _default_manager.upload_base_dir


def save_workflow_to_disk():
    """Save the default app's workflows to disk (BC wrapper)."""
    _default_manager.save_workflow_to_disk()


def load_workflow_from_disk():
    """Load workflows from disk into the default app (BC wrapper)."""
    _default_manager.load_workflow_from_disk()


def start_debug_broadcast():
    """Start the default app's SSE debug broadcast worker (BC wrapper)."""
    _default_manager.start_debug_broadcast()


def stop_debug_broadcast():
    """Stop the default app's SSE debug broadcast worker (BC wrapper)."""
    _default_manager.stop_debug_broadcast()
