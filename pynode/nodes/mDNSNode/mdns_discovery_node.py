"""
mDNS Discovery Node - Discovers services on the network via mDNS
"""

import json
import socket
import threading
import time
from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from .mdns_manager import MDNSServiceListener, MDNS_AVAILABLE

_info = Info()
_info.add_text("Discovers services on the local network using mDNS (multicast DNS). Listens for service advertisements and outputs discovered service information.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Control messages to trigger discovery refresh")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Discovered service information (single or array based on configuration)")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Service Type:", "mDNS service type to discover (e.g., _http._tcp.local.)"),
    ("Refresh Interval:", "Seconds between discovery refreshes (0 = no auto-refresh)"),
    ("Output Mode:", "Send each service separately or all as an array"),
    ("Auto Start:", "Start discovery automatically when workflow starts")
)
_info.add_header("Input Message")
_info.add_code("msg.payload.action").text(" - Control: 'refresh' to trigger immediate discovery").end()
_info.add_header("Output Message")
_info.add_code("msg.payload").text(" - Service information (single service or array of services)").end()
_info.add_code("msg.topic").text(" - 'mdns/discovery/service' or 'mdns/discovery/services'").end()


class MDNSDiscoveryNode(BaseNode):
    """
    Discovers services on the network via mDNS.
    Outputs discovered service information.
    """
    info = str(_info)
    display_name = 'mDNS Discovery'
    icon = '🔍'
    category = 'network'
    color = '#5BA5D5'
    border_color = '#3D7FA8'
    text_color = '#FFFFFF'
    input_count = 1  # Receives control commands
    output_count = 1  # Outputs discovered services
    
    DEFAULT_CONFIG = {
        'service_type': '_http._tcp.local.',
        'refresh_interval': '0',
        'output_mode': 'array',
        'auto_start': 'true'
    }
    
    properties = [
        {
            'name': 'service_type',
            'label': 'Service Type',
            'type': 'text',
            'help': 'mDNS service type to discover (e.g., _http._tcp.local.)',
            'default': '_http._tcp.local.'
        },
        {
            'name': 'refresh_interval',
            'label': 'Refresh Interval (seconds)',
            'type': 'text',
            'help': 'Seconds between automatic discovery refreshes (0 = no auto-refresh)',
            'default': '0'
        },
        {
            'name': 'output_mode',
            'label': 'Output Mode',
            'type': 'select',
            'options': [
                {'value': 'single', 'label': 'Each Service Separately'},
                {'value': 'array', 'label': 'All Services as Array'}
            ],
            'default': DEFAULT_CONFIG['output_mode'],
            'help': 'How to output discovered services'
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
            'help': 'Start discovery when workflow starts'
        },
        {
            'name': 'start_discovery',
            'label': 'Start Discovery',
            'type': 'button',
            'action': 'start_discovery'
        },
        {
            'name': 'stop_discovery',
            'label': 'Stop Discovery',
            'type': 'button',
            'action': 'stop_discovery'
        },
        {
            'name': 'refresh_now',
            'label': 'Refresh Now',
            'type': 'button',
            'action': 'refresh_now'
        }
    ]
    
    def __init__(self, node_id=None, name="mDNS Discovery"):
        super().__init__(node_id, name)
        self.zeroconf = None
        self.browser = None
        self.listener = None
        self.running = False
        self.discovered_services = {}
        self.refresh_thread = None
        self.stop_refresh = threading.Event()
    
    def _parse_service_info(self, info) -> dict:
        """Parse zeroconf ServiceInfo into a dictionary"""
        service_data = {}
        
        # Get addresses
        if info.addresses:
            addresses = [socket.inet_ntoa(addr) for addr in info.addresses]
            service_data['addresses'] = addresses
            service_data['address'] = addresses[0] if addresses else None
        
        # Get port
        service_data['port'] = info.port
        
        # Get server
        if info.server:
            service_data['server'] = info.server
        
        # Get service name and type
        service_data['name'] = info.name
        service_data['type'] = info.type
        
        # Parse properties
        if info.properties:
            properties = {}
            for key, value in info.properties.items():
                try:
                    if isinstance(value, bytes):
                        decoded_value = value.decode('utf-8')
                        # Try to parse as JSON
                        try:
                            properties[key.decode('utf-8') if isinstance(key, bytes) else key] = json.loads(decoded_value)
                        except:
                            properties[key.decode('utf-8') if isinstance(key, bytes) else key] = decoded_value
                    else:
                        properties[key.decode('utf-8') if isinstance(key, bytes) else key] = value
                except:
                    pass
            service_data['properties'] = properties
        
        return service_data
    
    def _refresh_services(self):
        """Refresh and output current discovered services"""
        if not self.running or not self.listener:
            return
        
        # Get current services from listener
        services = []
        for name, info in self.listener.discovered_services.items():
            service_data = self._parse_service_info(info)
            services.append(service_data)
        
        # Output based on mode
        output_mode = self.config.get('output_mode', 'array')
        
        if output_mode == 'single':
            # Send each service as a separate message
            for service in services:
                msg = self.create_message(
                    service,
                    topic='mdns/discovery/service'
                )
                self.send(msg)
        else:
            # Send all services as an array
            msg = self.create_message(
                services,
                topic='mdns/discovery/services'
            )
            self.send(msg)
    
    def _refresh_worker(self):
        """Background worker for periodic refresh"""
        try:
            refresh_interval = self.get_config_int('refresh_interval', 0)
        except ValueError:
            refresh_interval = 0
        
        if refresh_interval <= 0:
            return
        
        while not self.stop_refresh.wait(refresh_interval):
            if self.running:
                self._refresh_services()
    
    def start_discovery(self):
        """Start mDNS discovery"""
        if not MDNS_AVAILABLE:
            self.report_error("zeroconf package not installed. Install with: pip install zeroconf")
            return
        
        if self.running:
            return  # Already running
        
        try:
            from zeroconf import Zeroconf, ServiceBrowser
            
            service_type = self.config.get('service_type', '_http._tcp.local.')
            
            # Create custom listener that stores discovered services
            class DiscoveryListener(MDNSServiceListener):
                def __init__(self, node):
                    super().__init__(standalone_mode=False)
                    self.node = node
                    self.discovered_services = {}
                
                def add_service(self, zc, service_type: str, name: str) -> None:
                    if not MDNS_AVAILABLE:
                        return
                    info = zc.get_service_info(service_type, name)
                    if info:
                        self.discovered_services[name] = info
                        # Trigger immediate output if not in array mode
                        if self.node.config.get('output_mode', 'array') == 'single':
                            service_data = self.node._parse_service_info(info)
                            msg = self.node.create_message(
                                service_data,
                                topic='mdns/discovery/service'
                            )
                            self.node.send(msg)
                
                def update_service(self, zc, service_type: str, name: str) -> None:
                    if not MDNS_AVAILABLE:
                        return
                    info = zc.get_service_info(service_type, name)
                    if info:
                        self.discovered_services[name] = info
                
                def remove_service(self, zc, service_type: str, name: str) -> None:
                    if name in self.discovered_services:
                        del self.discovered_services[name]
            
            # Create Zeroconf instance and browser
            self.zeroconf = Zeroconf()
            self.listener = DiscoveryListener(self)
            self.browser = ServiceBrowser(self.zeroconf, service_type, self.listener)
            self.running = True
            
            # Start refresh thread if interval is set
            try:
                refresh_interval = self.get_config_int('refresh_interval', 0)
            except ValueError:
                refresh_interval = 0
            
            if refresh_interval > 0:
                self.stop_refresh.clear()
                self.refresh_thread = threading.Thread(target=self._refresh_worker, daemon=True)
                self.refresh_thread.start()
            
            # Send initial refresh after a short delay to allow services to be discovered
            def initial_refresh():
                time.sleep(2)  # Wait 2 seconds for initial discoveries
                if self.running:
                    self._refresh_services()
            
            threading.Thread(target=initial_refresh, daemon=True).start()
            
            # Send status message
            msg = self.create_message({
                'status': 'discovering',
                'service_type': service_type,
                'refresh_interval': refresh_interval,
                'output_mode': self.config.get('output_mode', 'array')
            }, topic='mdns/discovery/started')
            self.send(msg)
            
        except Exception as e:
            self.report_error(f"Failed to start mDNS discovery: {str(e)}")
    
    def stop_discovery(self):
        """Stop mDNS discovery"""
        if not self.running:
            return
        
        self.running = False
        
        # Stop refresh thread
        if self.refresh_thread:
            self.stop_refresh.set()
            self.refresh_thread.join(timeout=2)
            self.refresh_thread = None
        
        # Close zeroconf
        if self.zeroconf:
            try:
                self.zeroconf.close()
            except:
                pass
            self.zeroconf = None
        
        self.browser = None
        self.listener = None
        
        # Send stopped message
        msg = self.create_message({
            'status': 'stopped'
        }, topic='mdns/discovery/stopped')
        self.send(msg)
    
    def refresh_now(self):
        """Manually trigger a discovery refresh"""
        if self.running:
            self._refresh_services()
    
    def on_input(self, msg: dict, input_index: int = 0):
        """
        Handle incoming messages to control discovery
        
        Expected message formats:
        - Control: {'payload': {'action': 'start'|'stop'|'refresh'}}
        """
        payload = msg.get('payload', {})
        
        if isinstance(payload, dict):
            action = payload.get('action', '').lower()
            
            if action == 'start':
                self.start_discovery()
            elif action == 'stop':
                self.stop_discovery()
            elif action == 'refresh':
                self.refresh_now()
    
    def on_start(self):
        """Start the node and optionally begin discovery"""
        super().on_start()
        
        # Auto-start if configured
        if self.get_config_bool('auto_start', True):
            self.start_discovery()
    
    def on_stop(self):
        """Stop discovery when node stops"""
        self.stop_discovery()
        super().on_stop()
