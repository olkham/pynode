"""
REST Endpoint Node - Exposes HTTP REST endpoints for external integration.

This node creates REST API endpoints that can be called externally to inject
messages into the workflow. Supports GET, POST, PUT, DELETE methods with
configurable paths and response handling.
"""

import json
import threading
import logging
from typing import Optional, Dict, Any, List
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import time

try:
    from ..base_node import BaseNode, MessageKeys, Info
except ImportError:
    from base_node import BaseNode, MessageKeys, Info

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text("Exposes HTTP REST endpoints for external integration. Creates configurable API endpoints that can receive HTTP requests and inject them into the workflow.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Response control messages (when responseMode is 'wait')"))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "HTTP request data with:"),
)
_info.add_bullets(
    ("req.method:", "HTTP method (GET, POST, etc.)"),
    ("req.path:", "Request path"),
    ("req.query:", "Query parameters"),
    ("req.headers:", "Request headers"),
    ("req.body:", "Request body (parsed JSON or raw)"),
    ("payload:", "Request body or query parameters"),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Port:", "HTTP server port (1024-65535)"),
    ("Endpoint Path:", "URL path for the endpoint"),
    ("Methods:", "Allowed HTTP methods"),
    ("Response Mode:", "How to respond to requests (immediate, wait, custom)"),
    ("Authentication:", "Optional auth (none, basic, bearer, API key)"),
)


class RESTEndpointNode(BaseNode):
    """
    REST Endpoint Node - Creates HTTP endpoints for external integration.
    
    This node starts an HTTP server that listens for incoming requests on
    configurable paths. When a request is received, it creates a message
    containing the request details and sends it through the workflow.
    
    Features:
    - Configurable HTTP methods (GET, POST, PUT, DELETE, PATCH)
    - Custom endpoint paths
    - Request body parsing (JSON, form data)
    - Query parameter extraction
    - Header access
    - Configurable response handling
    """
    
    # Visual properties
    display_name = 'REST Endpoint'
    info = str(_info)
    icon = '🌐'
    category = 'network'
    color = '#87CEEB'
    border_color = '#4682B4'
    text_color = '#000000'
    input_count = 1  # For dynamic response control
    output_count = 1
    
    DEFAULT_CONFIG = {
        'port': 9999,
        'path': '/api/webhook',
        'methods': 'POST',
        'responseMode': 'immediate',
        'responseCode': 200,
        'responseBody': '{"status": "received"}',
        'cors': True,
        'authType': 'none',
        'authCredentials': ''
    }
    
    properties = [
        {
            'name': 'port',
            'label': 'Port',
            'type': 'number',
            'placeholder': DEFAULT_CONFIG['port'],
            'default': DEFAULT_CONFIG['port']
        },
        {
            'name': 'path',
            'label': 'Endpoint Path',
            'type': 'text',
            'placeholder': '/api/webhook',
            'default': DEFAULT_CONFIG['path']
        },
        {
            'name': 'methods',
            'label': 'Allowed Methods',
            'type': 'select',
            'options': [
                {'value': 'GET', 'label': 'GET'},
                {'value': 'POST', 'label': 'POST'},
                {'value': 'PUT', 'label': 'PUT'},
                {'value': 'DELETE', 'label': 'DELETE'},
                {'value': 'PATCH', 'label': 'PATCH'},
                {'value': 'ALL', 'label': 'All Methods'}
            ],
            'default': DEFAULT_CONFIG['methods']
        },
        {
            'name': 'responseMode',
            'label': 'Response Mode',
            'type': 'select',
            'options': [
                {'value': 'immediate', 'label': 'Immediate (200 OK)'},
                {'value': 'wait', 'label': 'Wait for Response'},
                {'value': 'custom', 'label': 'Custom Status'}
            ],
            'default': DEFAULT_CONFIG['responseMode']
        },
        {
            'name': 'responseCode',
            'label': 'Response Code',
            'type': 'text',
            'placeholder': '200',
            'default': DEFAULT_CONFIG['responseCode']
        },
        {
            'name': 'responseBody',
            'label': 'Response Body',
            'type': 'text',
            'placeholder': DEFAULT_CONFIG['responseBody'],
            'default': DEFAULT_CONFIG['responseBody']
        },
        {
            'name': 'cors',
            'label': 'Enable CORS',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['cors']
        },
        {
            'name': 'authType',
            'label': 'Authentication',
            'type': 'select',
            'options': [
                {'value': 'none', 'label': 'None'},
                {'value': 'basic', 'label': 'Basic Auth'},
                {'value': 'bearer', 'label': 'Bearer Token'},
                {'value': 'apikey', 'label': 'API Key'}
            ],
            'default': DEFAULT_CONFIG['authType']
        },
        {
            'name': 'authCredentials',
            'label': 'Auth Credentials',
            'type': 'text',
            'placeholder': 'username:password or token',
            'showIf': {'authType': ['basic', 'bearer', 'apikey']},
            'default': DEFAULT_CONFIG['authCredentials']
        }
    ]
    
    def __init__(self, node_id: Optional[str] = None, name: str = "rest-endpoint"):
        super().__init__(node_id, name)
        self.configure(self.DEFAULT_CONFIG.copy())
        self.server: Optional[HTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self._running = False
        self._request_count = 0
        self._pending_responses: Dict[str, Any] = {}
        self._response_events: Dict[str, threading.Event] = {}
    
    def on_deploy(self):
        """Called when the workflow is deployed - start the server."""
        self._start_server()
    
    def on_start(self):
        """Called when the workflow starts."""
        if not self._running:
            self._start_server()
    
    def on_stop(self):
        """Called when the workflow stops."""
        self._stop_server()
    
    def on_close(self):
        """Called when the node is removed."""
        self._stop_server()
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Handle incoming messages for response control.
        
        When responseMode is 'wait', this allows the workflow to send
        a response back to the HTTP client.
        """
        request_id = msg.get('_request_id')
        if request_id and request_id in self._response_events:
            # Store the response data
            self._pending_responses[request_id] = {
                'status': msg.get('statusCode', 200),
                'body': msg.get(MessageKeys.PAYLOAD, ''),
                'headers': msg.get('headers', {})
            }
            # Signal that response is ready
            self._response_events[request_id].set()
        else:
            # Pass through if not a response message
            self.send(msg)
    
    def _create_handler(self):
        """Create a request handler class with access to node instance."""
        node = self
        
        class RESTRequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                logger.debug(f"REST Endpoint [{node.name}]: {format % args}")
            
            def _send_cors_headers(self):
                if node.config.get('cors', True):
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Access-Control-Allow-Methods', 
                                   'GET, POST, PUT, DELETE, PATCH, OPTIONS')
                    self.send_header('Access-Control-Allow-Headers', 
                                   'Content-Type, Authorization, X-API-Key')
            
            def _check_auth(self) -> bool:
                auth_type = node.config.get('authType', 'none')
                credentials = node.config.get('authCredentials', '')
                
                if auth_type == 'none':
                    return True
                
                if auth_type == 'basic':
                    auth_header = self.headers.get('Authorization', '')
                    if auth_header.startswith('Basic '):
                        import base64
                        try:
                            decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
                            return decoded == credentials
                        except Exception:
                            return False
                    return False
                
                if auth_type == 'bearer':
                    auth_header = self.headers.get('Authorization', '')
                    if auth_header.startswith('Bearer '):
                        return auth_header[7:] == credentials
                    return False
                
                if auth_type == 'apikey':
                    api_key = self.headers.get('X-API-Key', '')
                    return api_key == credentials
                
                return False
            
            def _check_method(self, method: str) -> bool:
                allowed = node.config.get('methods', 'POST')
                if allowed == 'ALL':
                    return True
                return method == allowed
            
            def _check_path(self) -> bool:
                expected_path = node.config.get('path', '/api/webhook')
                parsed = urlparse(self.path)
                return parsed.path == expected_path
            
            def _handle_request(self, method: str):
                # Check path
                if not self._check_path():
                    self.send_response(404)
                    self._send_cors_headers()
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"error": "Not Found"}')
                    return
                
                # Check method
                if not self._check_method(method):
                    self.send_response(405)
                    self._send_cors_headers()
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"error": "Method Not Allowed"}')
                    return
                
                # Check auth
                if not self._check_auth():
                    self.send_response(401)
                    self._send_cors_headers()
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"error": "Unauthorized"}')
                    return
                
                # Parse request
                parsed = urlparse(self.path)
                query_params = parse_qs(parsed.query)
                
                # Read body for POST/PUT/PATCH
                body = None
                content_length = self.headers.get('Content-Length')
                if content_length:
                    raw_body = self.rfile.read(int(content_length))
                    content_type = self.headers.get('Content-Type', '')
                    
                    if 'application/json' in content_type:
                        try:
                            body = json.loads(raw_body.decode('utf-8'))
                        except json.JSONDecodeError:
                            body = raw_body.decode('utf-8')
                    elif 'application/x-www-form-urlencoded' in content_type:
                        body = parse_qs(raw_body.decode('utf-8'))
                    else:
                        try:
                            body = raw_body.decode('utf-8')
                        except UnicodeDecodeError:
                            body = raw_body
                
                # Extract headers
                headers = dict(self.headers)
                
                # Create request ID for response tracking
                import uuid
                request_id = str(uuid.uuid4())
                
                # Build message
                msg = node.create_message(
                    payload=body if body is not None else query_params,
                    topic=f"http/{method.lower()}{parsed.path}"
                )
                msg['req'] = {
                    'method': method,
                    'path': parsed.path,
                    'query': query_params,
                    'headers': headers,
                    'body': body,
                    'url': self.path,
                    'client_address': self.client_address[0]
                }
                msg['_request_id'] = request_id
                
                node._request_count += 1
                
                # Handle response based on mode
                response_mode = node.config.get('responseMode', 'immediate')
                
                if response_mode == 'wait':
                    # Set up event for waiting
                    event = threading.Event()
                    node._response_events[request_id] = event
                    
                    # Send message through workflow
                    node.send(msg)
                    
                    # Wait for response (with timeout)
                    if event.wait(timeout=30):
                        response_data = node._pending_responses.pop(request_id, {})
                        status = response_data.get('status', 200)
                        body_content = response_data.get('body', '')
                        extra_headers = response_data.get('headers', {})
                        
                        self.send_response(status)
                        self._send_cors_headers()
                        for k, v in extra_headers.items():
                            self.send_header(k, v)
                        if 'Content-Type' not in extra_headers:
                            self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        
                        if isinstance(body_content, (dict, list)):
                            self.wfile.write(json.dumps(body_content).encode('utf-8'))
                        else:
                            self.wfile.write(str(body_content).encode('utf-8'))
                    else:
                        # Timeout
                        self.send_response(504)
                        self._send_cors_headers()
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(b'{"error": "Gateway Timeout"}')
                    
                    # Cleanup
                    node._response_events.pop(request_id, None)
                    node._pending_responses.pop(request_id, None)
                else:
                    # Immediate response
                    node.send(msg)
                    
                    status = node.config.get('responseCode', 200)
                    body_str = node.config.get('responseBody', '{"status": "received"}')
                    
                    self.send_response(status)
                    self._send_cors_headers()
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(body_str.encode('utf-8'))
            
            def do_OPTIONS(self):
                self.send_response(200)
                self._send_cors_headers()
                self.end_headers()
            
            def do_GET(self):
                self._handle_request('GET')
            
            def do_POST(self):
                self._handle_request('POST')
            
            def do_PUT(self):
                self._handle_request('PUT')
            
            def do_DELETE(self):
                self._handle_request('DELETE')
            
            def do_PATCH(self):
                self._handle_request('PATCH')
        
        return RESTRequestHandler
    
    def _start_server(self):
        """Start the HTTP server."""
        if self._running:
            return
        
        port = int(self.config.get('port', 8080))
        
        try:
            handler = self._create_handler()
            self.server = HTTPServer(('0.0.0.0', port), handler)
            self._running = True
            
            self.server_thread = threading.Thread(
                target=self._run_server,
                daemon=True,
                name=f"RESTEndpoint-{self.id}"
            )
            self.server_thread.start()
            
            path = self.config.get('path', '/api/webhook')
            logger.info(f"REST Endpoint [{self.name}] started on port {port} at {path}")
            self.set_status('running', f"Listening on :{port}{path}")
            
        except OSError as e:
            logger.error(f"REST Endpoint [{self.name}] failed to start: {e}")
            self.set_status('error', f"Port {port} in use")
            self._running = False
    
    def _run_server(self):
        """Server main loop."""
        while self._running and self.server:
            try:
                self.server.handle_request()
            except Exception as e:
                if self._running:
                    logger.error(f"REST Endpoint [{self.name}] error: {e}")
    
    def _stop_server(self):
        """Stop the HTTP server."""
        self._running = False
        
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass
            self.server = None
        
        # Clear pending responses
        for event in self._response_events.values():
            event.set()
        self._response_events.clear()
        self._pending_responses.clear()
        
        logger.info(f"REST Endpoint [{self.name}] stopped")
        self.set_status('stopped', 'Server stopped')
    
    def restart_server(self):
        """Restart the HTTP server."""
        self._stop_server()
        time.sleep(0.5)
        self._start_server()
