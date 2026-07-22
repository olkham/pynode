"""
Socket Node package - generic UDP and TCP messaging nodes.

Send and receive PyNode messages over plain UDP or TCP sockets - to another
PyNode instance, or to any external program that speaks the documented wire
format (a Node-RED flow, a microcontroller, a logging service, ...).

Two transports, same message semantics:

* ``UdpOutNode`` / ``UdpInNode`` - chunked UDP using the PNB1 wire protocol
  in ``udp_protocol.py``. Binary-native and drop-friendly; best for
  sustained high-rate video frames.
* ``TcpOutNode`` / ``TcpInNode`` - newline-delimited JSON over TCP
  (``ndjson_protocol.py``). Reliable/ordered and trivial to consume (a plain
  socket read split on newlines, then JSON.parse); best for
  control/telemetry/detections.

The ``interop/`` subfolder holds a standalone ``udp_probe.py`` diagnostic and
an optional ready-to-import Node-RED example flow (one common consumer).
"""

from .udp_out_node import UdpOutNode
from .udp_in_node import UdpInNode
from .tcp_out_node import TcpOutNode
from .tcp_in_node import TcpInNode

__all__ = ['UdpOutNode', 'UdpInNode',
           'TcpOutNode', 'TcpInNode']
