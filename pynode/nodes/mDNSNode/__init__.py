"""
mDNS Node - Service discovery using mDNS/Zeroconf
"""

from .mdns_broadcast_node import MDNSBroadcastNode
from .mdns_discovery_node import MDNSDiscoveryNode

# For compatibility with auto-discovery, export both as separate discoverable nodes
# The main __init__ will find both classes
MDNSBroadcastNode = MDNSBroadcastNode
MDNSDiscoveryNode = MDNSDiscoveryNode

__all__ = ['MDNSBroadcastNode', 'MDNSDiscoveryNode']
