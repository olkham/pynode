"""
Node-RED Node package - high-performance PyNode <-> Node-RED bridges.

Two transports, same message semantics:

* ``NodeRedOutNode`` / ``NodeRedInNode`` - chunked UDP using the PNB1 wire
  protocol in ``bridge_protocol.py``. Binary-native and drop-friendly; best
  for sustained high-rate video frames. The Node-RED side needs the bundled
  function-node flow.
* ``NodeRedTcpOutNode`` / ``NodeRedTcpInNode`` - newline-delimited JSON over
  TCP (``ndjson_protocol.py``). Reliable/ordered and needs ZERO custom
  Node-RED code to receive (core tcp-in + json nodes); best for
  control/telemetry/detections.

The ``nodered/`` subfolder contains the matching Node-RED-side flow
(importable JSON + README) covering both transports with core nodes only.
"""

from .nodered_out_node import NodeRedOutNode
from .nodered_in_node import NodeRedInNode
from .nodered_tcp_out_node import NodeRedTcpOutNode
from .nodered_tcp_in_node import NodeRedTcpInNode

__all__ = ['NodeRedOutNode', 'NodeRedInNode',
           'NodeRedTcpOutNode', 'NodeRedTcpInNode']
