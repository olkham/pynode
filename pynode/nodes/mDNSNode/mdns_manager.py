import json
import socket
import threading
import logging
from typing import Dict, Any


# Try to import zeroconf for mDNS support
try:
    from zeroconf import ServiceListener as ZeroconfServiceListener
    MDNS_AVAILABLE = True
    # Use the real ServiceListener from zeroconf
    ServiceListenerBase = ZeroconfServiceListener
except ImportError:
    MDNS_AVAILABLE = False
    # Create dummy base class if zeroconf not available
    class ServiceListenerBase:  # type: ignore
        """Dummy ServiceListener base class when zeroconf is not available"""
        pass


class MDNSServiceListener(ServiceListenerBase):  # type: ignore
    """Listener for mDNS service discovery events"""
    
    def __init__(self, discovery_manager):
        self.discovery_manager = discovery_manager
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def add_service(self, zc, service_type: str, name: str) -> None:
        """Called when a service is discovered"""
        if not MDNS_AVAILABLE:
            return
        info = zc.get_service_info(service_type, name)

    
    def update_service(self, zc, service_type: str, name: str) -> None:
        """Called when a service is updated"""
        if not MDNS_AVAILABLE:
            return
        info = zc.get_service_info(service_type, name)

    def remove_service(self, zc, service_type: str, name: str) -> None:
        """Called when a service is removed"""
        # Extract node_id from service name
        node_id = name.split('.')[0] if '.' in name else name
        if node_id in self.discovery_manager.discovered_nodes:
            node_name = self.discovery_manager.discovered_nodes[node_id].node_name
            self.discovery_manager.discovered_nodes[node_id].mark_offline()
            self.logger.info(f"mDNS service removed: {node_name} ({node_id})")
    

class MDNSBroadcaster:
    """Handles mDNS service broadcasting for node discovery"""
    
    def __init__(self, node_id: str, node_info: Dict[str, Any], service_port: int, service_type: str = "_http._tcp.local."):
        """
        Initialize mDNS broadcaster
        
        Args:
            node_id: Unique identifier for this node
            node_info: Dictionary containing node information
            service_port: Port number where the service is running
            service_type: mDNS service type (default: "_http._tcp.local.")
        """
        self.node_id = node_id
        self.node_info = node_info
        self.service_port = service_port
        self.service_type = service_type
        self.zeroconf = None
        self.service_info = None
        self.logger = logging.getLogger(self.__class__.__name__)
        self.running = False
        
        if not MDNS_AVAILABLE:
            self.logger.warning("zeroconf package not available. mDNS broadcasting disabled.")
            self.logger.info("Install with: pip install zeroconf")
    
    def start(self):
        """Start mDNS service broadcasting"""
        if not MDNS_AVAILABLE:
            self.logger.warning("Cannot start mDNS: zeroconf package not installed")
            return False
        
        if self.running:
            self.logger.warning("mDNS broadcaster already running")
            return True
        
        try:
            from zeroconf import Zeroconf, ServiceInfo
            
            self.zeroconf = Zeroconf()

            service_name = f"{self.node_id}.{self.service_type}"
            
            # Get local IP address (using the same method as network scan to get actual network IP)
            try:
                # Connect to external address to determine local network IP
                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                temp_sock.connect(("8.8.8.8", 80))
                local_ip = temp_sock.getsockname()[0]
                temp_sock.close()
            except Exception as e:
                # Fallback to hostname resolution if the above fails
                self.logger.warning(f"Failed to get network IP via connection test: {e}")
                hostname = socket.gethostname()
                local_ip = socket.gethostbyname(hostname)
            
            hostname = socket.gethostname()
            
            # Prepare service properties from node_info
            # Convert all values to strings and handle complex types as JSON
            properties = {}
            for key, value in self.node_info.items():
                if isinstance(value, (dict, list)):
                    # Serialize complex types as JSON
                    properties[key] = json.dumps(value)
                else:
                    # Convert simple types to strings
                    properties[key] = str(value)
            
            # Create service info
            self.service_info = ServiceInfo(
                self.service_type,
                service_name,
                addresses=[socket.inet_aton(local_ip)],
                port=self.service_port,
                properties=properties,
                server=f"{hostname}.local."
            )
            
            # Register service
            self.zeroconf.register_service(self.service_info)
            self.running = True
            
            self.logger.info(f"mDNS service registered: {service_name} on {local_ip}:{self.service_port}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start mDNS broadcaster: {str(e)}")
            return False
    
    def stop(self):
        """Stop mDNS service broadcasting"""
        if not self.running:
            return
        
        try:
            if self.zeroconf and self.service_info:
                self.zeroconf.unregister_service(self.service_info)
                self.zeroconf.close()
            
            self.running = False
            self.logger.info("mDNS service unregistered")
            
        except Exception as e:
            self.logger.error(f"Error stopping mDNS broadcaster: {str(e)}")
    
    def update_info(self, node_info: Dict[str, Any]):
        """Update node information and re-register service"""
        self.node_info = node_info
        if self.running:
            self.stop()
            self.start()



if __name__ == "__main__":
    """Standalone mDNS broadcaster for testing"""
    import argparse
    import sys
    
    class KeyValueAction(argparse.Action):
        """Custom action to parse key=value pairs"""
        def __call__(self, parser, namespace, values, option_string=None):
            if not hasattr(namespace, 'properties'):
                namespace.properties = {}
            for value in values:
                if '=' not in value:
                    raise argparse.ArgumentTypeError(f"Invalid format: '{value}'. Expected key=value")
                key, val = value.split('=', 1)
                # Try to parse value as JSON for lists/dicts/booleans/numbers
                try:
                    namespace.properties[key] = json.loads(val)
                except json.JSONDecodeError:
                    # If not valid JSON, treat as string
                    namespace.properties[key] = val
    
    parser = argparse.ArgumentParser(
        description='mDNS service broadcaster for device discovery',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Basic usage
  python mdns_manager.py --node-id my-node --node-name "My Node" --port 5000
  
  # Add custom properties with key=value pairs
  python mdns_manager.py --node-id prod-01 --node-name "Production" --port 5555 \\
      --property platform=Windows cpu_count=8 memory_gb=16
  
  # Properties support JSON values for complex types
  python mdns_manager.py --node-id gpu-node --node-name "GPU Node" \\
      --property available_engines='["ultralytics","onnx"]' \\
                 gpu='{"available":true,"type":"NVIDIA","count":2}'
  
  # Mix of simple and complex properties
  python mdns_manager.py --node-id test --node-name "Test" \\
      --property platform=Linux cpu_count=4 version=1.2.3 \\
                 tags='["production","inference"]'
        '''
    )
    
    # Required arguments
    parser.add_argument('--node-id', 
                        required=True,
                        help='Unique identifier for this node')
    parser.add_argument('--node-name', 
                        required=True,
                        help='Human-readable name for this node')
    parser.add_argument('--port', 
                        type=int, 
                        required=True,
                        help='Service port number')
    parser.add_argument('--service-type',
                        type=str,
                        default='_http._tcp.local.',
                        help='mDNS service type (default: _http._tcp.local.)')
    
    # Generic property arguments
    parser.add_argument('--property',
                        nargs='+',
                        action=KeyValueAction,
                        metavar='KEY=VALUE',
                        help='Additional properties as key=value pairs (supports JSON values)')
    
    # Debug options
    parser.add_argument('--debug', 
                        action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--quiet', 
                        action='store_true',
                        help='Suppress all but error messages')
    
    args = parser.parse_args()
    
    # Configure logging
    if args.debug:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.ERROR
    else:
        log_level = logging.INFO
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    # Check if zeroconf is available
    if not MDNS_AVAILABLE:
        logger.error("zeroconf package not installed. Install with: pip install zeroconf")
        sys.exit(1)
    
    # Build node info dictionary from properties
    node_info = {
        'node_name': args.node_name,
        'api_port': args.port
    }
    
    # Add any additional properties provided via --property
    if hasattr(args, 'properties') and args.properties:
        node_info.update(args.properties)
    
    logger.info(f"Starting mDNS broadcaster for node: {args.node_name} ({args.node_id})")
    logger.info(f"Service port: {args.port}")
    
    # Log all properties
    if hasattr(args, 'properties') and args.properties:
        logger.info("Node properties:")
        for key, value in args.properties.items():
            logger.info(f"  {key}: {value}")
    
    # Create and start broadcaster
    mdns_broadcaster = MDNSBroadcaster(args.node_id, node_info, args.port, args.service_type)
    
    if mdns_broadcaster.start():
        logger.info("mDNS broadcaster started successfully")
        logger.info("Service will be discoverable on the local network")
        try:
            input("\nPress Enter to stop the broadcaster...\n")
        except KeyboardInterrupt:
            logger.info("\nReceived interrupt signal")
        finally:
            logger.info("Stopping mDNS broadcaster...")
            mdns_broadcaster.stop()
            logger.info("mDNS broadcaster stopped")
    else:
        logger.error("Failed to start mDNS broadcaster")
        sys.exit(1)