"""Server-Sent Events debug stream.

The broadcast worker itself lives on the WorkflowManager
(``manager.start_debug_broadcast()`` / ``manager.stop_debug_broadcast()``) so
each app instance has its own worker thread and client queues.
"""

import json
import logging
import queue

from flask import Blueprint, Response, stream_with_context

from pynode.api.helpers import _get_manager

logger = logging.getLogger(__name__)

sse_bp = Blueprint('sse', __name__)


@sse_bp.route('/api/debug/stream')
def debug_stream():
    """Server-Sent Events stream for debug messages."""
    manager = _get_manager()

    def generate():
        # Create a queue for this client
        q = queue.Queue(maxsize=100)
        client_id = id(q)
        with manager.clients_lock:
            manager.debug_message_queues[client_id] = q

        # Start broadcast thread if not running
        manager.start_debug_broadcast()

        try:
            yield 'data: {"type": "connected"}\n\n'

            while True:
                try:
                    # Wait for data from broadcast thread
                    data = q.get(timeout=1.0)
                    yield f'data: {json.dumps(data)}\n\n'
                except queue.Empty:
                    # Send keepalive
                    yield 'data: {"type": "keepalive"}\n\n'

        except GeneratorExit:
            # Client disconnected
            with manager.clients_lock:
                manager.debug_message_queues.pop(client_id, None)
        except Exception as e:
            # Log error and close connection
            logger.error(f"SSE Error: {e}")
            with manager.clients_lock:
                manager.debug_message_queues.pop(client_id, None)

    return Response(stream_with_context(generate()), mimetype='text/event-stream')
