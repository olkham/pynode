"""
PyNode - A Node-RED-like Visual Workflow System with Python Backend

This is a complete system for creating visual workflows with Python nodes.
Each node represents a function/operation and can be connected to create data pipelines.

Quick Start:
1. Install: pip install -e .
2. Run: pynode
3. Open browser: http://localhost:5000

Usage Example:
    from pynode.workflow_engine import WorkflowEngine
    from pynode.nodes import InjectNode, DebugNode

    engine = WorkflowEngine()
    engine.register_node_type(InjectNode)
    engine.register_node_type(DebugNode)

    inject = engine.create_node('InjectNode', name='my_inject')
    debug = engine.create_node('DebugNode', name='my_debug')
    engine.connect_nodes(inject.id, debug.id)
    engine.start()
"""

import argparse
import logging
import logging.handlers
import os
import signal

logger = logging.getLogger(__name__)

LOG_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
DEFAULT_THREADS = 32
_LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1'}


def _env_int(name, default):
    """Read a positive int from the environment, falling back on bad input."""
    try:
        value = int(os.environ.get(name, ''))
    except ValueError:
        return default
    return value if value > 0 else default


def configure_logging(level_name, log_file=None):
    """Configure root logging: console always, plus an optional rotating file."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file = os.path.abspath(os.path.expanduser(log_file))
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        # 5 x 10 MB: a long-running deployment must not fill the disk.
        handlers.append(logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'))
    logging.basicConfig(
        level=getattr(logging, str(level_name).upper(), logging.INFO),
        format=LOG_FORMAT, handlers=handlers, force=True)


def exposure_warning(host, api_key):
    """Return a warning when the server is reachable off-host without auth.

    PyNode executes user-supplied Python (Function nodes) and reads/writes
    files, so an unauthenticated listener on a routable interface hands code
    execution to anyone who can reach the port.
    """
    if api_key or host in _LOOPBACK_HOSTS:
        return None
    return (
        f"Listening on {host} WITHOUT an API key: anyone who can reach this port "
        "can run code on this machine via Function nodes. Set --api-key / "
        "PYNODE_API_KEY, or bind to 127.0.0.1 (--host 127.0.0.1) and put an "
        "authenticating reverse proxy in front.")


def install_signal_handlers():
    """Turn SIGTERM (docker stop, systemd, k8s) into a clean interrupt.

    Python only converts SIGINT to KeyboardInterrupt. Without this, SIGTERM
    kills the process mid-write: video files are left without an index, CSV /
    JSON sinks lose buffered rows and cameras are not released.
    """
    def _terminate(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")

    for name in ('SIGTERM', 'SIGBREAK'):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _terminate)
        except (ValueError, OSError):
            # Not the main thread, or the platform refuses this signal.
            pass


def main():
    """Main entry point for PyNode application."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='PyNode Visual Workflow System')
    parser.add_argument('--production', action='store_true',
                        help='Run in production mode using Waitress server')
    parser.add_argument('--host', default='0.0.0.0',
                        help='Host address to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5000,
                        help='Port to bind to (default: 5000)')
    parser.add_argument('--log-level', default='INFO',
                        help='Logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO')
    parser.add_argument('--log-file', default=None,
                        help='Also write logs to this file, rotated at 10 MB '
                             '(5 backups kept). Also settable via the '
                             'PYNODE_LOG_FILE env var. Default: console only.')
    parser.add_argument('--threads', type=int, default=None,
                        help='Request-handling threads in production mode. Every '
                             'open browser tab (event stream) and every live video '
                             'stream holds one, so size this for your viewers. Also '
                             f'settable via PYNODE_THREADS. Default: {DEFAULT_THREADS}.')
    parser.add_argument('--cors-origins', default=None,
                        help='Comma-separated list of allowed CORS origins '
                             '(default: * i.e. all origins). '
                             'Also settable via the PYNODE_CORS_ORIGINS env var.')
    parser.add_argument('--api-key', default=None,
                        help='Require this API key on all /api/ requests '
                             '(X-API-Key header or api_key query parameter). '
                             'Also settable via the PYNODE_API_KEY env var. '
                             'Default: no authentication.')
    parser.add_argument('--data-dir', default=None,
                        help='Directory for PyNode data; workflows are '
                             'persisted under <data-dir>/workflows/. '
                             'Also settable via the PYNODE_DATA_DIR env var. '
                             'Default: the source checkout root when running '
                             'from a checkout, otherwise ~/.pynode.')
    parser.add_argument('--models-dir', default=None,
                        help='Directory for shared model weights (YOLO .pt '
                             'files, exported OpenVINO models, etc.). '
                             'Also settable via the PYNODE_MODELS_DIR env var. '
                             'Default: <data-dir>/models.')
    args = parser.parse_args()

    # Configure application-wide logging
    configure_logging(args.log_level, args.log_file or os.environ.get('PYNODE_LOG_FILE'))

    # CORS and the data directory are configured when pynode.server is first
    # imported (it builds the module-level default app), so the CLI flags
    # must be exported to the environment BEFORE the import below.
    # (This is why the server import lives inside main() rather than at
    # module top.) The env var names live in pynode.config.
    if args.cors_origins is not None:
        os.environ['PYNODE_CORS_ORIGINS'] = args.cors_origins
    if args.data_dir is not None:
        os.environ['PYNODE_DATA_DIR'] = args.data_dir
    # Node code (which has no Flask app context) resolves the models dir from
    # the env var / defaults, so export the CLI flag before the server import.
    if args.models_dir is not None:
        os.environ['PYNODE_MODELS_DIR'] = args.models_dir

    from pynode.server import app, load_workflow_from_disk, shutdown_default_app

    # The API key is read dynamically from app.config on every request, so
    # it can simply be set after import. CLI flag wins over the env var
    # (which server.py already applied as the app.config default).
    if args.api_key is not None:
        app.config['PYNODE_API_KEY'] = args.api_key

    if app.config.get('PYNODE_API_KEY'):
        logger.info("API key authentication ENABLED: /api/ requests require "
                    "the X-API-Key header or api_key query parameter")
    if args.cors_origins is not None:
        logger.info(f"CORS allowed origins: {args.cors_origins}")

    warning = exposure_warning(args.host, app.config.get('PYNODE_API_KEY'))
    if warning:
        logger.warning(warning)

    # Load workflow from disk on startup
    logger.info("Loading workflow from disk...")
    load_workflow_from_disk()

    install_signal_handlers()
    try:
        _serve(app, args)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        # Stop every engine so nodes run their on_stop: writers finalise
        # their files, sinks flush, cameras and sockets are released.
        logger.info("Stopping workflows...")
        try:
            shutdown_default_app()
        except Exception:
            logger.exception("Error while stopping workflows")
        logger.info("PyNode stopped")


def _serve(app, args):
    """Run the HTTP server until interrupted."""
    if args.production:
        # Production mode with Waitress
        try:
            from waitress import serve
        except ImportError:
            logger.error("waitress not installed. Install with: pip install waitress")
            logger.warning("Falling back to development server...")
        else:
            threads = args.threads if args.threads and args.threads > 0 else _env_int(
                'PYNODE_THREADS', DEFAULT_THREADS)
            logger.info("Starting PyNode server in PRODUCTION mode...")
            logger.info(f"Server running at: http://{args.host}:{args.port} ({threads} threads)")
            serve(app, host=args.host, port=args.port, threads=threads,
                  channel_timeout=120, backlog=1024, connection_limit=1000)
            return
    else:
        logger.info("Starting PyNode server in DEVELOPMENT mode...")
        logger.info("For production use: pynode --production")

    logger.info(f"Server running at: http://{args.host}:{args.port}")
    app.run(debug=False, host=args.host, port=args.port, threaded=True)


if __name__ == '__main__':
    main()
