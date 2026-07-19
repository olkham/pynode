"""
Node-RED Node package - a high-performance PyNode <-> Node-RED UDP bridge.

``NodeRedOutNode`` / ``NodeRedInNode`` send/receive messages using the PNB1
wire protocol implemented in ``bridge_protocol.py`` (pure, stdlib-only,
shared by both nodes and their tests). The ``nodered/`` subfolder contains
the matching Node-RED-side flow (importable JSON + README) that implements
the same protocol with core Node-RED nodes only.
"""

from .nodered_out_node import NodeRedOutNode
from .nodered_in_node import NodeRedInNode

__all__ = ['NodeRedOutNode', 'NodeRedInNode']
