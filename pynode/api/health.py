"""Health endpoints for orchestrators and monitoring.

``GET /healthz``
    Liveness probe. Deliberately outside ``/api/`` so it needs no API key (a
    container runtime or load balancer cannot be handed one) and deliberately
    cheap: it answers 200 as long as the process can serve a request. It
    reveals nothing about the deployment.

``GET /api/health``
    Detailed status behind the normal API-key check: version, uptime and the
    run state of every workflow. Always 200 while the server is up - a stopped
    workflow is a legitimate state, so alert on the ``running`` flags instead.
"""

import time

from flask import Blueprint, jsonify

from pynode.api.helpers import _get_manager

health_bp = Blueprint('health', __name__)

_STARTED_AT = time.monotonic()


def _version() -> str:
    try:
        from pynode import __version__
        return str(__version__)
    except Exception:
        return 'unknown'


@health_bp.route('/healthz', methods=['GET'])
def liveness():
    """Unauthenticated liveness probe."""
    return jsonify({'status': 'ok'}), 200


@health_bp.route('/api/health', methods=['GET'])
def health():
    """Detailed health: version, uptime and per-workflow run state."""
    manager = _get_manager()
    with manager.state_lock:
        snapshot = [
            (wid, dict(meta), manager.deployed_engines.get(wid))
            for wid, meta in manager.workflows.items()
        ]

    workflows = []
    for wid, meta, engine in snapshot:
        workflows.append({
            'id': wid,
            'name': meta.get('name', ''),
            'enabled': bool(meta.get('enabled', True)),
            'running': bool(engine.running) if engine is not None else False,
            'nodes': len(engine.nodes) if engine is not None else 0,
        })

    return jsonify({
        'success': True,
        'status': 'ok',
        'version': _version(),
        'uptime_seconds': round(time.monotonic() - _STARTED_AT, 1),
        'workflow_count': len(workflows),
        'running_count': sum(1 for w in workflows if w['running']),
        'workflows': workflows,
    }), 200
