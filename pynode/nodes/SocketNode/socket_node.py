"""
Socket Node - UDP and TCP network communication.

This node provides bidirectional UDP and TCP socket communication.
It can operate as a client (sending data) or server (receiving data)
for both protocols.
"""

import socket
import threading
import logging
import json
import struct
import time
from typing import Optional, Dict, Any, List, Tuple
from queue import Queue, Empty

try:
    from ..base_node import BaseNode, MessageKeys, Info
except ImportError:
    from base_node import BaseNode, MessageKeys, Info

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text("Provides UDP and TCP network communication. Operates as client (sending data) or server (receiving data) for both protocols.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Data to send over network"))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Received data from network and status messages"),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Protocol:", "UDP or TCP"),
    ("Mode:", "Client (send) or Server (listen)"),
    ("Host/IP:", "Target address for client mode"),
    ("Port:", "Network port number"),
    ("Data Format:", "String, JSON, binary, or hex"),
    ("Framing:", "Message framing for TCP (newline, null byte, length-prefixed)"),
)


class SocketNode(BaseNode):
    """
    Socket Node - UDP and TCP network communication.
    
    This node provides flexible network socket functionality supporting
    both UDP and TCP protocols. It can operate in multiple modes:
    
    Modes:
    - UDP Client: Send UDP datagrams to a target
    - UDP Server: Listen for incoming UDP datagrams
    - TCP Client: Connect to a TCP server and send/receive data
    - TCP Server: Accept TCP connections and handle data
    
    Features:
    - Configurable protocols (UDP/TCP)
    - Client and server modes
    - Multiple data formats (raw, string, JSON, binary)
    - Message framing options for TCP
    - Broadcast support for UDP
    - Connection management for TCP
    - Non-blocking operation
    """
    
    # Visual properties
    display_name = 'Socket'
    info = str(_info)
    icon = '🔌'
    category = 'network'
    color = '#DDA0DD'
    border_color = '#9932CC'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'protocol': 'udp',
        'mode': 'client',
        'host': '127.0.0.1',
        'port': 9000,
        'bindAddress': '0.0.0.0',
        'dataFormat': 'string',
        'framing': 'newline',
        'broadcast': False,
        'bufferSize': 65535,
        'timeout': 10,
        'maxConnections': 10,
        'keepAlive': True,
        'autoReconnect': True,
        'reconnectDelay': 5000
    }
    
    properties = [
        {
            'name': 'protocol',
            'label': 'Protocol',
            'type': 'select',
            'options': [
                {'value': 'udp', 'label': 'UDP'},
                {'value': 'tcp', 'label': 'TCP'}
            ]
        },
        {
            'name': 'mode',
            'label': 'Mode',
            'type': 'select',
            'options': [
                {'value': 'client', 'label': 'Client (Send)'},
                {'value': 'server', 'label': 'Server (Listen)'}
            ]
        },
        {
            'name': 'host',
            'label': 'Host/IP',
            'type': 'text',
            'placeholder': 'IP address or hostname'
        },
        {
            'name': 'port',
            'label': 'Port',
            'type': 'text',
            'placeholder': '9000'
        },
        {
            'name': 'bindAddress',
            'label': 'Bind Address (Server)',
            'type': 'text',
            'placeholder': '0.0.0.0 for all interfaces',
            'showIf': {'mode': 'server'}
        },
        {
            'name': 'dataFormat',
            'label': 'Data Format',
            'type': 'select',
            'options': [
                {'value': 'string', 'label': 'String (UTF-8)'},
                {'value': 'json', 'label': 'JSON'},
                {'value': 'binary', 'label': 'Binary (bytes)'},
                {'value': 'hex', 'label': 'Hex String'}
            ]
        },
        {
            'name': 'framing',
            'label': 'Message Framing (TCP)',
            'type': 'select',
            'options': [
                {'value': 'none', 'label': 'None (stream)'},
                {'value': 'newline', 'label': 'Newline (\\n)'},
                {'value': 'null', 'label': 'Null byte (\\0)'},
                {'value': 'length', 'label': 'Length-prefixed (4 bytes)'},
                {'value': 'crlf', 'label': 'CRLF (\\r\\n)'}
            ],
            'showIf': {'protocol': 'tcp'}
        },
        {
            'name': 'broadcast',
            'label': 'UDP Broadcast',
            'type': 'checkbox',
            'default': False,
            'showIf': {'protocol': 'udp'}
        },
        {
            'name': 'bufferSize',
            'label': 'Buffer Size',
            'type': 'text',
            'placeholder': '65535'
        },
        {
            'name': 'timeout',
            'label': 'Timeout (seconds)',
            'type': 'text',
            'placeholder': '10'
        },
        {
            'name': 'maxConnections',
            'label': 'Max Connections (TCP Server)',
            'type': 'text',
            'placeholder': '10',
            'showIf': {'protocol': 'tcp', 'mode': 'server'}
        },
        {
            'name': 'keepAlive',
            'label': 'TCP Keep Alive',
            'type': 'checkbox',
            'default': True,
            'showIf': {'protocol': 'tcp'}
        },
        {
            'name': 'autoReconnect',
            'label': 'Auto Reconnect (TCP Client)',
            'type': 'checkbox',
            'default': True,
            'showIf': {'protocol': 'tcp', 'mode': 'client'}
        },
        {
            'name': 'reconnectDelay',
            'label': 'Reconnect Delay (ms)',
            'type': 'text',
            'placeholder': '5000',
            'showIf': {'protocol': 'tcp', 'mode': 'client', 'autoReconnect': True}
        }
    ]
    
    def __init__(self, node_id: Optional[str] = None, name: str = "socket"):
        super().__init__(node_id, name)
        self.configure(self.DEFAULT_CONFIG.copy())
        
        self._socket: Optional[socket.socket] = None
        self._server_thread: Optional[threading.Thread] = None
        self._client_threads: List[threading.Thread] = []
        self._running = False
        self._connected = False
        
        self._sent_count = 0
        self._received_count = 0
        self._active_connections = 0
        
        self._tcp_clients: Dict[str, socket.socket] = {}
        self._tcp_client_lock = threading.Lock()
        self._receive_buffer = b''
    
    def on_deploy(self):
        """Called when workflow is deployed."""
        self._start()
    
    def on_start(self):
        """Called when workflow starts."""
        if not self._running:
            self._start()
    
    def on_stop(self):
        """Called when workflow stops."""
        self._stop()
    
    def on_close(self):
        """Called when node is removed."""
        self._stop()
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Handle incoming messages - send data out."""
        protocol = self.config.get('protocol', 'udp')
        mode = self.config.get('mode', 'client')
        
        # Get payload and format it
        payload = msg.get(MessageKeys.PAYLOAD)
        data = self._format_outgoing_data(payload)
        
        if data is None:
            logger.warning(f"Socket [{self.name}] cannot format payload for sending")
            return
        
        # Get target from message or config
        host = msg.get('host', self.config.get('host', '127.0.0.1'))
        port = msg.get('port', self.config.get('port', 9000))
        
        try:
            if protocol == 'udp':
                self._send_udp(data, host, port)
            else:
                # TCP client mode
                if mode == 'client':
                    self._send_tcp_client(data)
                else:
                    # TCP server - send to specific or all clients
                    client_id = msg.get('client_id')
                    self._send_tcp_server(data, client_id)
            
            self._sent_count += 1
            
        except Exception as e:
            logger.error(f"Socket [{self.name}] send error: {e}")
            self.report_error(f"Send error: {e}")
    
    def _start(self):
        """Start the socket based on configuration."""
        if self._running:
            return
        
        self._running = True
        protocol = self.config.get('protocol', 'udp')
        mode = self.config.get('mode', 'client')
        
        if protocol == 'udp':
            if mode == 'server':
                self._start_udp_server()
            else:
                self._setup_udp_client()
        else:
            if mode == 'server':
                self._start_tcp_server()
            else:
                self._start_tcp_client()
    
    def _stop(self):
        """Stop all socket operations."""
        self._running = False
        self._connected = False
        
        # Close main socket
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        
        # Close all TCP clients
        with self._tcp_client_lock:
            for client_socket in self._tcp_clients.values():
                try:
                    client_socket.close()
                except Exception:
                    pass
            self._tcp_clients.clear()
        
        self._active_connections = 0
    
    # ========================
    # UDP Implementation
    # ========================
    
    def _setup_udp_client(self):
        """Setup UDP client socket."""
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            if self.config.get('broadcast', False):
                self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            
            self._connected = True
            logger.info(f"Socket [{self.name}] UDP client ready")
            
        except Exception as e:
            logger.error(f"Socket [{self.name}] UDP client setup failed: {e}")
            self.report_error(f"UDP client setup failed: {e}")
    
    def _start_udp_server(self):
        """Start UDP server."""
        bind_addr = self.config.get('bindAddress', '0.0.0.0')
        port = int(self.config.get('port', 9000))
        
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind((bind_addr, port))
            self._socket.settimeout(1.0)  # For checking _running flag
            
            self._connected = True
            
            # Start receive thread
            self._server_thread = threading.Thread(
                target=self._udp_receive_loop,
                daemon=True,
                name=f"Socket-UDP-{self.id}"
            )
            self._server_thread.start()
            
            logger.info(f"Socket [{self.name}] UDP server listening on {bind_addr}:{port}")
            
        except Exception as e:
            logger.error(f"Socket [{self.name}] UDP server start failed: {e}")
            self.report_error(f"UDP server start failed: {e}")
    
    def _udp_receive_loop(self):
        """UDP receive loop."""
        buffer_size = int(self.config.get('bufferSize', 65535))
        
        while self._running and self._socket:
            try:
                data, addr = self._socket.recvfrom(buffer_size)
                self._received_count += 1
                
                # Parse and send message
                payload = self._parse_incoming_data(data)
                msg = self.create_message(
                    payload=payload,
                    topic=f"udp/{addr[0]}:{addr[1]}"
                )
                msg['remote'] = {
                    'address': addr[0],
                    'port': addr[1],
                    'protocol': 'udp'
                }
                self.send(msg, output_index=0)
                
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Socket [{self.name}] UDP receive error: {e}")
    
    def _send_udp(self, data: bytes, host: str, port: int):
        """Send UDP datagram."""
        if not self._socket:
            self._setup_udp_client()
        
        if self._socket:
            self._socket.sendto(data, (host, port))
    
    # ========================
    # TCP Implementation
    # ========================
    
    def _start_tcp_server(self):
        """Start TCP server."""
        bind_addr = self.config.get('bindAddress', '0.0.0.0')
        port = int(self.config.get('port', 9000))
        max_conn = int(self.config.get('maxConnections', 10))
        
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind((bind_addr, port))
            self._socket.listen(max_conn)
            self._socket.settimeout(1.0)
            
            self._connected = True
            
            # Start accept thread
            self._server_thread = threading.Thread(
                target=self._tcp_accept_loop,
                daemon=True,
                name=f"Socket-TCP-Accept-{self.id}"
            )
            self._server_thread.start()
            
            logger.info(f"Socket [{self.name}] TCP server listening on {bind_addr}:{port}")
            
        except Exception as e:
            logger.error(f"Socket [{self.name}] TCP server start failed: {e}")
            self.report_error(f"TCP server start failed: {e}")
    
    def _tcp_accept_loop(self):
        """TCP connection accept loop."""
        while self._running and self._socket:
            try:
                client_socket, addr = self._socket.accept()
                client_id = f"{addr[0]}:{addr[1]}"
                
                # Configure client socket
                if self.config.get('keepAlive', True):
                    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                
                timeout = float(self.config.get('timeout', 10))
                if timeout > 0:
                    client_socket.settimeout(timeout)
                
                # Store client
                with self._tcp_client_lock:
                    self._tcp_clients[client_id] = client_socket
                    self._active_connections = len(self._tcp_clients)
                
                # Start receive thread for this client
                thread = threading.Thread(
                    target=self._tcp_client_receive_loop,
                    args=(client_socket, client_id),
                    daemon=True,
                    name=f"Socket-TCP-Client-{client_id}"
                )
                thread.start()
                self._client_threads.append(thread)
                
                # Send connection status
                self._send_status_message('connected', client_id)
                logger.info(f"Socket [{self.name}] TCP client connected: {client_id}")
                
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Socket [{self.name}] TCP accept error: {e}")
    
    def _tcp_client_receive_loop(self, client_socket: socket.socket, client_id: str):
        """TCP client receive loop."""
        buffer_size = int(self.config.get('bufferSize', 65535))
        buffer = b''
        
        while self._running:
            try:
                data = client_socket.recv(buffer_size)
                if not data:
                    break  # Connection closed
                
                buffer += data
                
                # Process complete messages based on framing
                messages, buffer = self._extract_framed_messages(buffer)
                
                for message_data in messages:
                    self._received_count += 1
                    payload = self._parse_incoming_data(message_data)
                    
                    msg = self.create_message(
                        payload=payload,
                        topic=f"tcp/{client_id}"
                    )
                    msg['remote'] = {
                        'address': client_id.split(':')[0],
                        'port': int(client_id.split(':')[1]),
                        'protocol': 'tcp',
                        'client_id': client_id
                    }
                    msg['client_id'] = client_id
                    self.send(msg, output_index=0)
                
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.debug(f"Socket [{self.name}] TCP receive error for {client_id}: {e}")
                break
        
        # Cleanup
        self._remove_tcp_client(client_id)
        self._send_status_message('disconnected', client_id)
        logger.info(f"Socket [{self.name}] TCP client disconnected: {client_id}")
    
    def _remove_tcp_client(self, client_id: str):
        """Remove a TCP client."""
        with self._tcp_client_lock:
            if client_id in self._tcp_clients:
                try:
                    self._tcp_clients[client_id].close()
                except Exception:
                    pass
                del self._tcp_clients[client_id]
                self._active_connections = len(self._tcp_clients)
    
    def _start_tcp_client(self):
        """Start TCP client connection."""
        host = self.config.get('host', '127.0.0.1')
        port = int(self.config.get('port', 9000))
        
        def connect():
            while self._running and not self._connected:
                try:
                    self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    
                    if self.config.get('keepAlive', True):
                        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    
                    timeout = float(self.config.get('timeout', 10))
                    if timeout > 0:
                        self._socket.settimeout(timeout)
                    
                    self._socket.connect((host, port))
                    self._connected = True
                    self._active_connections = 1
                    
                    # Start receive thread
                    self._server_thread = threading.Thread(
                        target=self._tcp_client_main_receive_loop,
                        daemon=True,
                        name=f"Socket-TCP-Recv-{self.id}"
                    )
                    self._server_thread.start()
                    
                    self._send_status_message('connected', f"{host}:{port}")
                    logger.info(f"Socket [{self.name}] TCP connected to {host}:{port}")
                    return
                    
                except Exception as e:
                    logger.warning(f"Socket [{self.name}] TCP connection failed: {e}")
                    self._socket = None
                    
                    if self.config.get('autoReconnect', True):
                        delay = int(self.config.get('reconnectDelay', 5000)) / 1000.0
                        time.sleep(delay)
                    else:
                        self.report_error(f"TCP connection failed: {e}")
                        return
        
        # Start connection in thread
        thread = threading.Thread(target=connect, daemon=True)
        thread.start()
    
    def _tcp_client_main_receive_loop(self):
        """TCP client receive loop (when acting as client)."""
        buffer_size = int(self.config.get('bufferSize', 65535))
        buffer = b''
        host = self.config.get('host', '127.0.0.1')
        port = self.config.get('port', 9000)
        
        while self._running and self._connected and self._socket:
            try:
                data = self._socket.recv(buffer_size)
                if not data:
                    break
                
                buffer += data
                messages, buffer = self._extract_framed_messages(buffer)
                
                for message_data in messages:
                    self._received_count += 1
                    payload = self._parse_incoming_data(message_data)
                    
                    msg = self.create_message(
                        payload=payload,
                        topic=f"tcp/{host}:{port}"
                    )
                    msg['remote'] = {
                        'address': host,
                        'port': port,
                        'protocol': 'tcp'
                    }
                    self.send(msg, output_index=0)
                
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Socket [{self.name}] TCP client receive error: {e}")
                break
        
        # Connection lost
        self._connected = False
        self._active_connections = 0
        self._send_status_message('disconnected', f"{host}:{port}")
        
        # Auto reconnect
        if self._running and self.config.get('autoReconnect', True):
            delay = int(self.config.get('reconnectDelay', 5000)) / 1000.0
            time.sleep(delay)
            if self._running:
                self._start_tcp_client()
    
    def _send_tcp_client(self, data: bytes):
        """Send data over TCP client connection."""
        if not self._connected or not self._socket:
            raise ConnectionError("Not connected")
        
        # Add framing
        framed_data = self._add_framing(data)
        self._socket.sendall(framed_data)
    
    def _send_tcp_server(self, data: bytes, client_id: Optional[str] = None):
        """Send data to TCP clients (server mode)."""
        framed_data = self._add_framing(data)
        
        with self._tcp_client_lock:
            if client_id:
                # Send to specific client
                if client_id in self._tcp_clients:
                    try:
                        self._tcp_clients[client_id].sendall(framed_data)
                    except Exception as e:
                        logger.error(f"Socket [{self.name}] send to {client_id} failed: {e}")
            else:
                # Broadcast to all clients
                for cid, client_socket in list(self._tcp_clients.items()):
                    try:
                        client_socket.sendall(framed_data)
                    except Exception as e:
                        logger.error(f"Socket [{self.name}] send to {cid} failed: {e}")
    
    # ========================
    # Data Formatting
    # ========================
    
    def _format_outgoing_data(self, payload: Any) -> Optional[bytes]:
        """Format payload for sending."""
        data_format = self.config.get('dataFormat', 'string')
        
        try:
            if data_format == 'string':
                if isinstance(payload, bytes):
                    return payload
                return str(payload).encode('utf-8')
            
            elif data_format == 'json':
                return json.dumps(payload).encode('utf-8')
            
            elif data_format == 'binary':
                if isinstance(payload, bytes):
                    return payload
                elif isinstance(payload, list):
                    return bytes(payload)
                return str(payload).encode('utf-8')
            
            elif data_format == 'hex':
                if isinstance(payload, str):
                    return bytes.fromhex(payload.replace(' ', ''))
                return str(payload).encode('utf-8')
            
            return str(payload).encode('utf-8')
            
        except Exception as e:
            logger.error(f"Socket [{self.name}] format error: {e}")
            return None
    
    def _parse_incoming_data(self, data: bytes) -> Any:
        """Parse incoming data."""
        data_format = self.config.get('dataFormat', 'string')
        
        try:
            if data_format == 'string':
                return data.decode('utf-8')
            
            elif data_format == 'json':
                return json.loads(data.decode('utf-8'))
            
            elif data_format == 'binary':
                return list(data)
            
            elif data_format == 'hex':
                return data.hex()
            
            return data.decode('utf-8')
            
        except Exception as e:
            logger.warning(f"Socket [{self.name}] parse error: {e}")
            return data
    
    def _add_framing(self, data: bytes) -> bytes:
        """Add framing to outgoing TCP data."""
        framing = self.config.get('framing', 'newline')
        
        if framing == 'newline':
            return data + b'\n'
        elif framing == 'null':
            return data + b'\x00'
        elif framing == 'crlf':
            return data + b'\r\n'
        elif framing == 'length':
            return struct.pack('>I', len(data)) + data
        else:
            return data
    
    def _extract_framed_messages(self, buffer: bytes) -> Tuple[List[bytes], bytes]:
        """Extract complete messages from buffer based on framing."""
        framing = self.config.get('framing', 'newline')
        messages = []
        
        if framing == 'newline':
            delimiter = b'\n'
        elif framing == 'null':
            delimiter = b'\x00'
        elif framing == 'crlf':
            delimiter = b'\r\n'
        elif framing == 'length':
            # Length-prefixed framing
            while len(buffer) >= 4:
                length = struct.unpack('>I', buffer[:4])[0]
                if len(buffer) >= 4 + length:
                    messages.append(buffer[4:4+length])
                    buffer = buffer[4+length:]
                else:
                    break
            return messages, buffer
        else:
            # No framing - return all data as one message
            if buffer:
                messages.append(buffer)
                buffer = b''
            return messages, buffer
        
        # Delimiter-based framing
        while delimiter in buffer:
            msg, buffer = buffer.split(delimiter, 1)
            if msg:
                messages.append(msg)
        
        return messages, buffer
    
    def _send_status_message(self, status: str, detail: str):
        """Send status message on main output with status topic."""
        msg = self.create_message(
            payload={'status': status, 'detail': detail},
            topic=f"socket/status/{status}"
        )
        self.send(msg)
    
    # ========================
    # Actions
    # ========================
    
    def reconnect(self, *args, **kwargs):
        """Action: Reconnect socket."""
        self._stop()
        time.sleep(0.5)
        self._start()
    
    def disconnect(self, *args, **kwargs):
        """Disconnect socket."""
        self._stop()
