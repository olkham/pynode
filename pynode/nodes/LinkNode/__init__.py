"""
Link Node package - Link In and Link Out nodes for cross-flow message passing.

Link Out publishes messages to a named channel on a process-wide bus; Link In
receives messages from a channel. Because both live in one process, they can
pass messages between separate workflows (Node-RED-style link nodes, but
channel-based instead of using a node picker).
"""

from .link_out_node import LinkOutNode
from .link_in_node import LinkInNode

__all__ = ['LinkOutNode', 'LinkInNode']
