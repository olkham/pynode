"""
mDNS Broadcast Node - Broadcasts service information over mDNS for discovery
"""

import json
from nodes.base_node import BaseNode
from .mdns_manager import MDNSBroadcaster, MDNS_AVAILABLE


class MDNSBroadcastNode(BaseNode):
    """
    Broadcasts information via mDNS for discovery by other nodes on the network.
    Broadcasts properties from incoming messages.
    """
    display_name = 'mDNS Broadcast'
    icon = '📡'
    category = 'network'
    color = '#5BA5D5'
    border_color = '#3D7FA8'
    text_color = '#FFFFFF'
    input_count = 1  # Receives broadcast information
    output_count = 1  # Passes through messages
    
    DEFAULT_CONFIG = {
        'node_id': '',
        'service_port': '5000',
        'service_type': '_http._tcp.local.',
        'auto_start': 'true'
    }
    
    properties = [
        {
            'name': 'node_id',
            'label': 'Node ID',
            'type': 'text',
            'help': 'Unique identifier for this service (auto-generated if empty)'
        },
        {
            'name': 'service_port',
            'label': 'Service Port',
            'type': 'text',
            'help': 'Port number where service is running (e.g., 5000)'
        },
        {
            'name': 'service_type',
            'label': 'Service Type',
            'type': 'text',
            'help': 'mDNS service type (default: _http._tcp.local.)',
            'default': '_http._tcp.local.'
        },
        {
            'name': 'auto_start',
            'label': 'Auto Start',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes'},
                {'value': 'false', 'label': 'No'}
            ],
            'default': DEFAULT_CONFIG['auto_start'],
            'help': 'Start broadcasting when workflow starts'
        },
        {
            'name': 'start_broadcast',
            'label': 'Start Broadcasting',
            'type': 'button',
            'action': 'start_broadcast'
        },
        {
            'name': 'stop_broadcast',
            'label': 'Stop Broadcasting',
            'type': 'button',
            'action': 'stop_broadcast'
        }
    ]
    
    def __init__(self, node_id=None, name="mDNS Broadcast"):
        super().__init__(node_id, name)
        self.broadcaster = None
        self.broadcast_info = {}
        self.configure(self.DEFAULT_CONFIG)
    
    
    def start_broadcast(self):
        """Start mDNS broadcasting"""
        if not MDNS_AVAILABLE:
            self.report_error("zeroconf package not installed. Install with: pip install zeroconf")
            return
        
        if self.broadcaster and self.broadcaster.running:
            return  # Already running
        
        # Get configuration
        node_id = self.config.get('node_id', '').strip()
        if not node_id:
            node_id = self.id  # Use node instance ID if not specified
        
        try:
            service_port = int(self.config.get('service_port', '5000'))
        except ValueError:
            self.report_error("Invalid service port number")
            return
        
        service_type = self.config.get('service_type', '_http._tcp.local.')
        
        # Create and start broadcaster with current broadcast info
        self.broadcaster = MDNSBroadcaster(node_id, self.broadcast_info, service_port, service_type)
        
        if self.broadcaster.start():
            # Send success message
            msg = self.create_message({
                'status': 'broadcasting',
                'node_id': node_id,
                'port': service_port,
                'service_type': service_type,
                'info': self.broadcast_info
            }, topic='mdns/broadcast/started')
            self.send(msg)
        else:
            self.report_error("Failed to start mDNS broadcaster")
    
    def stop_broadcast(self):
        """Stop mDNS broadcasting"""
        if self.broadcaster:
            self.broadcaster.stop()
            
            # Send stopped message
            msg = self.create_message({
                'status': 'stopped'
            }, topic='mdns/broadcast/stopped')
            self.send(msg)
    
    def on_input(self, msg: dict, input_index: int = 0):
        """
        Handle incoming messages to update broadcast information or control broadcasting
        
        Expected message formats:
        - Control: {'payload': {'action': 'start'|'stop'|'restart'}}
        - Broadcast data: {'broadcast': {'key': 'value', ...}}
        - Update broadcast: {'payload': {...}} - updates broadcast_info with payload contents
        """
        payload = msg.get('payload', {})
        
        # Check for broadcast data in message
        if 'broadcast' in msg:
            broadcast_data = msg.get('broadcast', {})
            if isinstance(broadcast_data, dict):
                # Update broadcast info with new data
                self.broadcast_info.update(broadcast_data)
                
                # Update broadcaster if running
                if self.broadcaster and self.broadcaster.running:
                    self.broadcaster.update_info(self.broadcast_info)
        
        # Handle control actions
        if isinstance(payload, dict):
            action = payload.get('action', '').lower()
            
            if action == 'start':
                self.start_broadcast()
                return
            elif action == 'stop':
                self.stop_broadcast()
                return
            elif action == 'restart':
                self.stop_broadcast()
                self.start_broadcast()
                return
            elif not action:
                # If no action specified, treat payload as broadcast data
                self.broadcast_info.update(payload)
                
                # Update broadcaster if running
                if self.broadcaster and self.broadcaster.running:
                    self.broadcaster.update_info(self.broadcast_info)
        
        # Pass through the message
        self.send(msg)
    
    def on_start(self):
        """Start the node and optionally begin broadcasting"""
        super().on_start()
        
        # Auto-start if configured
        if self.config.get('auto_start', 'true') == 'true':
            self.start_broadcast()
    
    def on_stop(self):
        """Stop broadcasting when node stops"""
        self.stop_broadcast()
        super().on_stop()
