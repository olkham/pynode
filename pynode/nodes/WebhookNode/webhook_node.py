"""
Webhook Node - Makes HTTP requests to external webhooks and APIs.

This node sends HTTP requests to configured endpoints when it receives
a message. Supports various HTTP methods, authentication options,
and flexible payload configuration.
"""

import json
import threading
import logging
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode
import time

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    # Fallback to urllib
    import urllib.request
    import urllib.error
    import ssl

try:
    from ..base_node import BaseNode, MessageKeys, Info
except ImportError:
    from base_node import BaseNode, MessageKeys, Info

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text("Makes HTTP requests to external webhooks and APIs. Sends configured HTTP requests when it receives a message.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Message to trigger HTTP request"))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "HTTP response with:"),
)
_info.add_bullets(
    ("payload.statusCode:", "HTTP status code (200, 404, 500, etc.)"),
    ("payload.body:", "Response body (parsed JSON or text)"),
    ("payload.headers:", "Response headers"),
    ("payload.url:", "Final URL after redirects"),
    ("payload.elapsed:", "Response time in seconds"),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("URL:", "Target endpoint URL"),
    ("Method:", "HTTP method (GET, POST, PUT, DELETE, PATCH)"),
    ("Content Type:", "Request content type (JSON, form, text)"),
    ("Authentication:", "Optional auth (none, basic, bearer, API key)"),
    ("Timeout:", "Request timeout in seconds"),
    ("Retries:", "Number of retry attempts on failure"),
)


class WebhookNode(BaseNode):
    """
    Webhook Node - Sends HTTP requests to external services.
    
    This node makes HTTP requests to external webhooks, REST APIs, or
    other HTTP endpoints. It supports various HTTP methods, authentication
    options, custom headers, and flexible payload configuration.
    
    Features:
    - Multiple HTTP methods (GET, POST, PUT, DELETE, PATCH)
    - Various authentication types (Basic, Bearer, API Key)
    - Custom headers
    - JSON and form-encoded payloads
    - Timeout configuration
    - Retry logic with exponential backoff
    - Response parsing and forwarding
    """
    
    # Visual properties
    display_name = 'Webhook'
    info = str(_info)
    icon = '📤'
    category = 'network'
    color = '#90EE90'
    border_color = '#228B22'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'url': '',
        'method': 'POST',
        'contentType': 'application/json',
        'payloadSource': 'msg.payload',
        'customPayload': '',
        'headers': '{}',
        'authType': 'none',
        'authCredentials': '',
        'apiKeyHeader': 'X-API-Key',
        'timeout': 30,
        'retries': 0,
        'retryDelay': 1000,
        'followRedirects': True,
        'validateSSL': False,
        'async': True
    }
    
    properties = [
        {
            'name': 'url',
            'label': 'URL',
            'type': 'text',
            'placeholder': 'https://api.example.com/webhook'
        },
        {
            'name': 'method',
            'label': 'Method',
            'type': 'select',
            'options': [
                {'value': 'GET', 'label': 'GET'},
                {'value': 'POST', 'label': 'POST'},
                {'value': 'PUT', 'label': 'PUT'},
                {'value': 'DELETE', 'label': 'DELETE'},
                {'value': 'PATCH', 'label': 'PATCH'}
            ],
            'default': DEFAULT_CONFIG['method']
            
        },
        {
            'name': 'contentType',
            'label': 'Content Type',
            'type': 'select',
            'options': [
                {'value': 'application/json', 'label': 'JSON'},
                {'value': 'application/x-www-form-urlencoded', 'label': 'Form URL Encoded'},
                {'value': 'text/plain', 'label': 'Plain Text'},
                {'value': 'custom', 'label': 'Custom (set in headers)'}
            ],
            'default': DEFAULT_CONFIG['contentType']
        },
        {
            'name': 'payloadSource',
            'label': 'Payload Source',
            'type': 'select',
            'options': [
                {'value': 'msg.payload', 'label': 'msg.payload'},
                {'value': 'msg', 'label': 'Entire Message'},
                {'value': 'custom', 'label': 'Custom Template'}
            ],
            'default': DEFAULT_CONFIG['payloadSource']
        },
        {
            'name': 'customPayload',
            'label': 'Custom Payload',
            'type': 'textarea',
            'placeholder': '{"key": "{{msg.payload}}"}',            
            'showIf': {'payloadSource': 'custom'},
            'default': DEFAULT_CONFIG['customPayload']
        },
        {
            'name': 'headers',
            'label': 'Headers (JSON)',
            'type': 'textarea',
            'placeholder': '{"X-Custom-Header": "value"}',
            'default': DEFAULT_CONFIG['headers']
        },
        {
            'name': 'authType',
            'label': 'Authentication',
            'type': 'select',
            'options': [
                {'value': 'none', 'label': 'None'},
                {'value': 'basic', 'label': 'Basic Auth'},
                {'value': 'bearer', 'label': 'Bearer Token'},
                {'value': 'apikey', 'label': 'API Key Header'}
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
        },
        {
            'name': 'apiKeyHeader',
            'label': 'API Key Header Name',
            'type': 'text',
            'placeholder': 'X-API-Key',
            'showIf': {'authType': 'apikey'},
            'default': DEFAULT_CONFIG['apiKeyHeader']
        },
        {
            'name': 'timeout',
            'label': 'Timeout (seconds)',
            'type': 'text',
            'placeholder': '30',
            'default': DEFAULT_CONFIG['timeout']
        },
        {
            'name': 'retries',
            'label': 'Retries',
            'type': 'text',
            'placeholder': '0',
            'default': DEFAULT_CONFIG['retries']
        },
        {
            'name': 'retryDelay',
            'label': 'Retry Delay (ms)',
            'type': 'text',
            'placeholder': '1000',
            'default': DEFAULT_CONFIG['retryDelay']
        },
        {
            'name': 'followRedirects',
            'label': 'Follow Redirects',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['followRedirects']
        },
        {
            'name': 'validateSSL',
            'label': 'Validate SSL',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['validateSSL']
        },
        {
            'name': 'async',
            'label': 'Async (non-blocking)',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['async']
        }
    ]
    
    def __init__(self, node_id: Optional[str] = None, name: str = "webhook"):
        super().__init__(node_id, name)
        self.configure(self.DEFAULT_CONFIG.copy())
        self._request_count = 0
        self._success_count = 0
        self._error_count = 0
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Handle incoming messages by making HTTP requests."""
        if self.config.get('async', True):
            # Non-blocking request in separate thread
            thread = threading.Thread(
                target=self._make_request,
                args=(msg,),
                daemon=True
            )
            thread.start()
        else:
            # Blocking request
            self._make_request(msg)
    
    def _make_request(self, msg: Dict[str, Any]):
        """Make the HTTP request."""
        self._request_count += 1
        
        # Get configuration
        url = self._resolve_template(self.config.get('url', ''), msg)
        method = self.config.get('method', 'POST')
        content_type = self.config.get('contentType', 'application/json')
        timeout = int(self.config.get('timeout', 30))
        retries = int(self.config.get('retries', 0))
        retry_delay = int(self.config.get('retryDelay', 1000)) / 1000.0
        
        # Build headers
        headers = self._build_headers(msg, content_type)
        
        # Build payload
        payload = self._build_payload(msg)
        
        # Make request with retries
        last_error = None
        for attempt in range(retries + 1):
            try:
                response = self._execute_request(
                    url, method, headers, payload, timeout
                )
                
                # Success
                self._success_count += 1
                self._handle_success(msg, response)
                return
                
            except Exception as e:
                last_error = e
                if attempt < retries:
                    logger.warning(
                        f"Webhook [{self.name}] attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
        
        # All retries failed
        self._error_count += 1
        self._handle_error(msg, last_error)
    
    def _build_headers(self, msg: Dict[str, Any], content_type: str) -> Dict[str, str]:
        """Build request headers."""
        headers = {}
        
        # Parse custom headers
        try:
            custom_headers = self.config.get('headers', '{}')
            if custom_headers:
                headers.update(json.loads(custom_headers))
        except json.JSONDecodeError:
            logger.warning(f"Webhook [{self.name}] invalid headers JSON")
        
        # Set content type
        if content_type != 'custom':
            headers['Content-Type'] = content_type
        
        # Add authentication
        auth_type = self.config.get('authType', 'none')
        credentials = self.config.get('authCredentials', '')
        
        if auth_type == 'basic' and credentials:
            import base64
            encoded = base64.b64encode(credentials.encode()).decode()
            headers['Authorization'] = f'Basic {encoded}'
        
        elif auth_type == 'bearer' and credentials:
            headers['Authorization'] = f'Bearer {credentials}'
        
        elif auth_type == 'apikey' and credentials:
            header_name = self.config.get('apiKeyHeader', 'X-API-Key')
            headers[header_name] = credentials
        
        return headers
    
    def _build_payload(self, msg: Dict[str, Any]) -> Any:
        """Build request payload."""
        source = self.config.get('payloadSource', 'msg.payload')
        
        if source == 'msg.payload':
            return msg.get(MessageKeys.PAYLOAD)
        
        elif source == 'msg':
            # Clone message without internal fields
            payload = {k: v for k, v in msg.items() if not k.startswith('_')}
            return payload
        
        elif source == 'custom':
            template = self.config.get('customPayload', '')
            if template:
                resolved = self._resolve_template(template, msg)
                try:
                    return json.loads(resolved)
                except json.JSONDecodeError:
                    return resolved
            return None
        
        return msg.get(MessageKeys.PAYLOAD)
    
    def _resolve_template(self, template: str, msg: Dict[str, Any]) -> str:
        """Resolve template variables like {{msg.payload}}."""
        import re
        
        def replace_var(match):
            var_path = match.group(1)
            parts = var_path.split('.')
            
            value = msg
            for part in parts:
                if part == 'msg':
                    continue
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    return match.group(0)  # Return original if not found
            
            if isinstance(value, (dict, list)):
                return json.dumps(value)
            return str(value)
        
        return re.sub(r'\{\{([\w.]+)\}\}', replace_var, template)
    
    def _execute_request(
        self, url: str, method: str, headers: Dict[str, str],
        payload: Any, timeout: int
    ) -> Dict[str, Any]:
        """Execute the HTTP request."""
        validate_ssl = self.config.get('validateSSL', True)
        follow_redirects = self.config.get('followRedirects', True)
        
        if REQUESTS_AVAILABLE:
            return self._request_with_requests(
                url, method, headers, payload, timeout,
                validate_ssl, follow_redirects
            )
        else:
            return self._request_with_urllib(
                url, method, headers, payload, timeout,
                validate_ssl
            )
    
    def _request_with_requests(
        self, url: str, method: str, headers: Dict[str, str],
        payload: Any, timeout: int, validate_ssl: bool,
        follow_redirects: bool
    ) -> Dict[str, Any]:
        """Make request using requests library."""
        content_type = headers.get('Content-Type', 'application/json')
        
        kwargs = {
            'headers': headers,
            'timeout': timeout,
            'verify': validate_ssl,
            'allow_redirects': follow_redirects
        }
        
        if method in ['POST', 'PUT', 'PATCH'] and payload is not None:
            if 'application/json' in content_type:
                kwargs['json'] = payload
            elif 'application/x-www-form-urlencoded' in content_type:
                kwargs['data'] = payload if isinstance(payload, dict) else str(payload)
            else:
                kwargs['data'] = payload if isinstance(payload, str) else json.dumps(payload)
        
        elif method == 'GET' and isinstance(payload, dict):
            kwargs['params'] = payload
        
        response = requests.request(method, url, **kwargs)
        
        return {
            'status_code': response.status_code,
            'headers': dict(response.headers),
            'body': self._parse_response_body(response.text, response.headers.get('Content-Type', '')),
            'url': response.url,
            'elapsed': response.elapsed.total_seconds()
        }
    
    def _request_with_urllib(
        self, url: str, method: str, headers: Dict[str, str],
        payload: Any, timeout: int, validate_ssl: bool
    ) -> Dict[str, Any]:
        """Make request using urllib (fallback)."""
        content_type = headers.get('Content-Type', 'application/json')
        
        # Prepare data
        data = None
        if method in ['POST', 'PUT', 'PATCH'] and payload is not None:
            if 'application/json' in content_type:
                data = json.dumps(payload).encode('utf-8')
            elif isinstance(payload, dict):
                data = urlencode(payload).encode('utf-8')
            else:
                data = str(payload).encode('utf-8')
        
        # Create request
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        
        # SSL context
        context = None
        if not validate_ssl:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
                body = response.read().decode('utf-8')
                return {
                    'status_code': response.status,
                    'headers': dict(response.headers),
                    'body': self._parse_response_body(body, response.headers.get('Content-Type', '')),
                    'url': response.url,
                    'elapsed': 0
                }
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8') if e.fp else ''
            return {
                'status_code': e.code,
                'headers': dict(e.headers),
                'body': self._parse_response_body(body, e.headers.get('Content-Type', '')),
                'url': url,
                'elapsed': 0
            }
    
    def _parse_response_body(self, body: str, content_type: str) -> Any:
        """Parse response body based on content type."""
        if 'application/json' in content_type:
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return body
        return body
    
    def _handle_success(self, original_msg: Dict[str, Any], response: Dict[str, Any]):
        """Handle successful response."""
        # Create message with response metadata in payload
        msg = self.create_message(
            payload={
                'statusCode': response['status_code'],
                'body': response['body'],
                'headers': response['headers'],
                'url': response['url'],
                'elapsed': response['elapsed']
            },
            topic=original_msg.get(MessageKeys.TOPIC, '')
        )
        
        # Preserve original message fields (except payload)
        for key in original_msg:
            if key not in msg and key != MessageKeys.PAYLOAD and not key.startswith('_'):
                msg[key] = original_msg[key]
        
        self.send(msg)
    
    def _handle_error(self, original_msg: Dict[str, Any], error: Exception):
        """Handle request error."""
        logger.error(f"Webhook [{self.name}] request failed: {error}")
        
        # Report error to global error handling
        self.report_error(f"HTTP request failed: {error}")
        
        # Send error message to output with metadata in payload
        msg = self.create_message(
            payload={
                'statusCode': 0,
                'error': str(error),
                'body': None,
                'headers': {},
                'url': self.config.get('url', ''),
                'elapsed': 0
            },
            topic=f"{original_msg.get(MessageKeys.TOPIC, '')}/error"
        )
        
        # Preserve original message fields (except payload)
        for key in original_msg:
            if key not in msg and key != MessageKeys.PAYLOAD and not key.startswith('_'):
                msg[key] = original_msg[key]
        
        self.send(msg)
