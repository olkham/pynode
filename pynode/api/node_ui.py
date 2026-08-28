"""Node-supplied editor assets (``ui_assets``).

Serves the JS/CSS a node type ships alongside its Python, so a node's custom
properties-panel editor lives in the node's own folder instead of in the
editor's global files.

Two deliberate design points:

* **Not under ``/api/``.** The API-key guard in :mod:`pynode.server` only
  challenges ``/api/`` paths, and the ``auth.js`` wrapper that attaches
  ``X-API-Key`` wraps ``window.fetch`` - which dynamic ``import()`` and
  ``<link rel=stylesheet>`` do not go through. Serving these under ``/api/``
  would 401 the whole editor the moment ``PYNODE_API_KEY`` is set.

* **Exact-match lookup, no path arithmetic.** The servable set is a dict built
  once at import time by :func:`pynode.node_registry._resolve_ui_assets`, which
  has already checked that every entry exists, resolves inside its declaring
  node's folder, and carries an allowlisted suffix. A request either matches a
  key in that dict or 404s, so traversal is structurally impossible rather than
  filtered-and-hopefully-correct.
"""

import logging

from flask import Blueprint, abort, send_file

from pynode import node_registry

logger = logging.getLogger(__name__)

node_ui_bp = Blueprint('node_ui', __name__)

# Explicit rather than guessed: some environments map .js to text/plain, which
# makes the browser refuse the module.
_MIME_TYPES = {
    '.js': 'text/javascript',
    '.css': 'text/css',
}


@node_ui_bp.route(f'{node_registry.UI_ASSET_URL_PREFIX}/<path:asset_path>', methods=['GET'])
def serve_node_ui_asset(asset_path):
    """Serve one declared node UI asset, or 404."""
    url_path = f'{node_registry.UI_ASSET_URL_PREFIX}/{asset_path}'
    file_path = node_registry.ui_asset_registry.get(url_path)
    if file_path is None:
        abort(404)

    suffix = file_path[file_path.rfind('.'):].lower() if '.' in file_path else ''
    response = send_file(file_path, mimetype=_MIME_TYPES.get(suffix), conditional=True)
    # The URL carries the file's mtime (see _resolve_ui_assets), so a given URL
    # really does name one immutable body.
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response
