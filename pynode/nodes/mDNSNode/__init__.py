"""
mDNS Node - Service discovery using mDNS/Zeroconf
"""

from .mdns_broadcast_node import MDNSBroadcastNode

# For compatibility with auto-discovery, export both as separate discoverable nodes
# The main __init__ will find both classes
MDNSBroadcastNode = MDNSBroadcastNode

__all__ = ['MDNSBroadcastNode']
