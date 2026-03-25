"""
vLLM Node - Sends images and prompts to a vLLM OpenAI-compatible server.

Calls the /v1/chat/completions endpoint with vision-language model support.
All configuration fields (server_url, model, system_prompt, prompt, etc.)
can be set in the UI and overridden at runtime via incoming message fields.
"""

import json
import base64
import threading
import logging
from typing import Optional, Dict, Any, List

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    import urllib.request
    import urllib.error
    import ssl

try:
    from ..base_node import BaseNode, MessageKeys, Info
except ImportError:
    from base_node import BaseNode, MessageKeys, Info

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Info panel
# ---------------------------------------------------------------------------
_info = Info()
_info.add_text(
    "Sends images and text prompts to a vLLM server using the "
    "OpenAI-compatible /v1/chat/completions endpoint."
)
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with image data and/or prompt text"),
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Model response"),
)
_info.add_bullets(
    ("payload.content:", "The model's text response"),
    ("payload.model:", "Model name used"),
    ("payload.usage:", "Token usage statistics"),
    ("payload.elapsed:", "Response time in seconds"),
)
_info.add_header("Configuration")
_info.add_text(
    "All fields below can be set in the properties panel. "
    "Any field can be overridden at runtime by the incoming message:"
)
_info.add_bullets(
    ("msg.payload.prompt:", "Override the user prompt"),
    ("msg.payload.system_prompt:", "Override the system prompt"),
    ("msg.payload.image:", "Image data (base64 string or image dict)"),
    ("msg.payload.server_url:", "Override the server URL"),
    ("msg.payload.model:", "Override the model name"),
    ("msg.payload.max_tokens:", "Override max tokens"),
)


class VLLMNode(BaseNode):
    """
    vLLM Node - Interface to vLLM OpenAI-compatible vision-language models.

    Builds an OpenAI chat completions request with optional image input
    and sends it to a vLLM server. Configuration can be set via the UI
    properties panel and overridden at runtime through incoming message fields.
    """

    display_name = 'vLLM'
    info = str(_info)
    icon = '🤖'
    category = 'AI'
    color = '#7C3AED'
    border_color = '#5B21B6'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1

    DEFAULT_CONFIG: Dict[str, Any] = {
        'server_url': 'http://localhost:8000',
        'model': 'Qwen/Qwen3.5-9B',
        'system_prompt': 'You are a helpful assistant that analyzes images.',
        'prompt': 'Describe what you see in this image.',
        'max_tokens': 1024,
        'timeout': 60,
        'enable_thinking': False,
        'image_path': 'payload.image',
    }

    properties = [
        {
            'name': 'server_url',
            'label': 'Server URL',
            'type': 'text',
            'placeholder': 'http://localhost:8000',
        },
        {
            'name': 'model',
            'label': 'Model',
            'type': 'text',
            'placeholder': 'Qwen/Qwen3.5-9B',
        },
        {
            'name': 'system_prompt',
            'label': 'System Prompt',
            'type': 'textarea',
            'placeholder': 'You are a helpful assistant.',
        },
        {
            'name': 'prompt',
            'label': 'User Prompt',
            'type': 'textarea',
            'placeholder': 'Describe what you see in this image.',
        },
        {
            'name': 'max_tokens',
            'label': 'Max Tokens',
            'type': 'text',
            'placeholder': '1024',
        },
        {
            'name': 'timeout',
            'label': 'Timeout (seconds)',
            'type': 'text',
            'placeholder': '60',
        },
        {
            'name': 'enable_thinking',
            'label': 'Enable Thinking',
            'type': 'checkbox',
            'default': False,
        },
        {
            'name': 'image_path',
            'label': 'Image Path in Message',
            'type': 'text',
            'placeholder': 'payload.image',
        },
    ]

    def __init__(self, node_id: Optional[str] = None, name: str = "vllm"):
        super().__init__(node_id, name)
        self.configure(self.DEFAULT_CONFIG.copy())

    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Handle incoming messages by calling vLLM in a background thread."""
        thread = threading.Thread(
            target=self._call_vllm,
            args=(msg,),
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # Resolve a config value, allowing msg override
    # ------------------------------------------------------------------
    def _resolve(self, msg: Dict[str, Any], key: str, default: Any = None) -> Any:
        """
        Get a value from msg.payload.{key} first, falling back to config.
        """
        payload = msg.get(MessageKeys.PAYLOAD)
        if isinstance(payload, dict) and key in payload:
            return payload[key]
        return self.config.get(key, default)

    # ------------------------------------------------------------------
    # Build the image data URL from various input formats
    # ------------------------------------------------------------------
    def _get_image_data_url(self, msg: Dict[str, Any]) -> Optional[str]:
        """
        Extract image from the message and return as a data URL string.
        Supports: base64 string, dict with data/encoding/format, numpy array.
        """
        image_path = self.config.get('image_path', 'payload.image')
        image_data = self._get_nested_value(msg, image_path)

        # Also check msg.payload.image as direct override
        payload = msg.get(MessageKeys.PAYLOAD)
        if image_data is None and isinstance(payload, dict):
            image_data = payload.get('image')

        if image_data is None:
            return None

        # Already a data URL
        if isinstance(image_data, str) and image_data.startswith('data:image'):
            return image_data

        # Raw base64 string
        if isinstance(image_data, str):
            return f'data:image/jpeg;base64,{image_data}'

        # Camera node dict format: {'format': 'jpeg', 'encoding': 'base64', 'data': '...'}
        if isinstance(image_data, dict):
            data = image_data.get('data')
            fmt = image_data.get('format', 'jpeg')
            encoding = image_data.get('encoding', '')

            if encoding == 'base64' and isinstance(data, str):
                return f'data:image/{fmt};base64,{data}'

            # numpy array inside dict — encode to JPEG base64
            try:
                import numpy as np
                import cv2
                if isinstance(data, np.ndarray):
                    ret, buf = cv2.imencode('.jpg', data)
                    if ret:
                        b64 = base64.b64encode(buf.tobytes()).decode('utf-8')
                        return f'data:image/jpeg;base64,{b64}'
            except ImportError:
                pass

        # Direct numpy array
        try:
            import numpy as np
            import cv2
            if isinstance(image_data, np.ndarray):
                ret, buf = cv2.imencode('.jpg', image_data)
                if ret:
                    b64 = base64.b64encode(buf.tobytes()).decode('utf-8')
                    return f'data:image/jpeg;base64,{b64}'
        except ImportError:
            pass

        self.report_error(f"Unsupported image format: {type(image_data).__name__}")
        return None

    # ------------------------------------------------------------------
    # Main request logic
    # ------------------------------------------------------------------
    def _call_vllm(self, msg: Dict[str, Any]):
        """Build the payload and call the vLLM chat completions endpoint."""
        import time as _time

        server_url = self._resolve(msg, 'server_url', self.DEFAULT_CONFIG['server_url'])
        model = self._resolve(msg, 'model', self.DEFAULT_CONFIG['model'])
        system_prompt = self._resolve(msg, 'system_prompt', self.DEFAULT_CONFIG['system_prompt'])
        prompt = self._resolve(msg, 'prompt', self.DEFAULT_CONFIG['prompt'])
        max_tokens = int(self._resolve(msg, 'max_tokens', self.DEFAULT_CONFIG['max_tokens']))
        timeout = int(self._resolve(msg, 'timeout', self.DEFAULT_CONFIG['timeout']))
        enable_thinking = self._resolve(msg, 'enable_thinking', self.DEFAULT_CONFIG['enable_thinking'])
        if isinstance(enable_thinking, str):
            enable_thinking = enable_thinking.lower() in ('true', '1', 'yes')

        # Build user content (text only, or text + image)
        user_content: Any
        image_url = self._get_image_data_url(msg)
        if image_url:
            user_content = [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": prompt},
            ]
        else:
            user_content = prompt

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})

        # Build request payload
        request_payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        
        request_payload["chat_template_kwargs"] = {"enable_thinking": enable_thinking}

        url = f"{server_url.rstrip('/')}/v1/chat/completions"
        start = _time.time()

        try:
            response_data = self._post_json(url, request_payload, timeout)
            elapsed = _time.time() - start

            # Extract content from response
            content = ''
            usage = {}
            if isinstance(response_data, dict):
                choices = response_data.get('choices', [])
                if choices:
                    content = choices[0].get('message', {}).get('content', '')
                usage = response_data.get('usage', {})

            out_msg = self.create_message(
                payload={
                    'content': content,
                    'model': model,
                    'usage': usage,
                    'elapsed': round(elapsed, 3),
                },
                topic=msg.get(MessageKeys.TOPIC, ''),
            )
            # Preserve non-internal fields from original message
            for key in msg:
                if key not in out_msg and key != MessageKeys.PAYLOAD and not key.startswith('_'):
                    out_msg[key] = msg[key]

            self.send(out_msg)

        except Exception as exc:
            elapsed = _time.time() - start
            logger.error("VLLMNode [%s] request failed: %s", self.name, exc)
            self.report_error(f"vLLM request failed: {exc}")

            out_msg = self.create_message(
                payload={
                    'content': None,
                    'error': str(exc),
                    'model': model,
                    'elapsed': round(elapsed, 3),
                },
                topic=f"{msg.get(MessageKeys.TOPIC, '')}/error",
            )
            self.send(out_msg)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _post_json(self, url: str, payload: Dict[str, Any], timeout: int) -> Any:
        """POST JSON and return parsed response. Uses requests if available."""
        data = json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json'}

        if REQUESTS_AVAILABLE:
            resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            return resp.json()

        # Fallback to urllib
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode('utf-8'))
