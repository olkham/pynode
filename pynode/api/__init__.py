"""API blueprints for the PyNode Flask server."""

from pynode.api.nodes import nodes_bp
from pynode.api.services import services_bp
from pynode.api.sse import sse_bp
from pynode.api.uploads import uploads_bp
from pynode.api.workflows import workflows_bp

ALL_BLUEPRINTS = (workflows_bp, nodes_bp, services_bp, uploads_bp, sse_bp)


def register_blueprints(app):
    """Register every API blueprint on the given Flask app."""
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
