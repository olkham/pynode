"""
Roboflow Upload Node - uploads images to a Roboflow project for annotation.
"""

import base64
import os
import tempfile
import threading
from datetime import datetime
from typing import Any, Dict
import numpy as np
import cv2

from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Uploads images to a Roboflow project for annotation and training.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message containing an image in any supported format (numpy array, base64 JPEG, camera dict).")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "The original message is passed through after upload.")
)
_info.add_header("Properties")
_info.add_bullets(
    ("API Key:", "Roboflow API key from workspace settings."),
    ("Workspace ID:", "Roboflow workspace identifier (e.g. my-workspace)."),
    ("Project ID:", "Roboflow project identifier (e.g. my-project)."),
    ("Split:", "Which dataset split to upload to (train, valid, or test)."),
    ("Batch Name:", "Name for the upload batch (optional)."),
    ("Rate Limit:", "Minimum seconds between uploads (0 = no limit).")
)
_info.add_header("Notes")
_info.add_text("Requires the roboflow package. The node connects to Roboflow when the workflow starts and disconnects when it stops.")


class RoboflowUploadNode(BaseNode):
    """Uploads images to Roboflow for annotation."""

    display_name = 'Roboflow Upload'
    icon = '\u2B06'
    category = 'output'
    color = '#6706CE'
    border_color = '#4A049A'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    info = str(_info)

    DEFAULT_CONFIG = {
        'api_key': '',
        'workspace_id': '',
        'project_id': '',
        'split': 'train',
        'batch_name': 'pynode',
        'rate_limit': 0,
        MessageKeys.DROP_MESSAGES: True
    }

    properties = [
        {
            'name': 'api_key',
            'label': 'API Key',
            'type': 'text',
            'default': '',
            'placeholder': 'Your Roboflow API key',
            'help': 'API key from Roboflow workspace settings'
        },
        {
            'name': 'workspace_id',
            'label': 'Workspace ID',
            'type': 'text',
            'default': '',
            'placeholder': 'e.g. my-workspace',
            'help': 'Roboflow workspace identifier'
        },
        {
            'name': 'project_id',
            'label': 'Project ID',
            'type': 'text',
            'default': '',
            'placeholder': 'e.g. my-project',
            'help': 'Roboflow project identifier'
        },
        {
            'name': 'split',
            'label': 'Dataset Split',
            'type': 'select',
            'options': [
                {'value': 'train', 'label': 'Train'},
                {'value': 'valid', 'label': 'Validation'},
                {'value': 'test', 'label': 'Test'}
            ],
            'default': 'train',
            'help': 'Which dataset split to upload images to'
        },
        {
            'name': 'batch_name',
            'label': 'Upload Batch Name',
            'type': 'text',
            'default': 'pynode',
            'placeholder': 'e.g. my-batch',
            'help': 'Name for the upload batch (optional)'
        },
        {
            'name': 'rate_limit',
            'label': 'Rate Limit (seconds)',
            'type': 'number',
            'default': 0,
            'min': 0,
            'help': 'Minimum seconds between uploads (0 = no limit)'
        },
        {
            'name': MessageKeys.DROP_MESSAGES,
            'label': 'Drop Messages When Busy',
            'type': 'checkbox',
            'default': True
        }
    ]

    def __init__(self, node_id=None, name="roboflow upload"):
        super().__init__(node_id, name)
        self._rf_project = None
        self._last_upload_time = 0.0
        self._lock = threading.Lock()

    def on_start(self):
        """Connect to Roboflow when the workflow starts."""
        super().on_start()
        self._connect()

    def on_stop(self):
        """Disconnect from Roboflow when the workflow stops."""
        self._rf_project = None
        super().on_stop()

    def configure(self, config: Dict[str, Any]):
        """Apply configuration."""
        super().configure(config)

    def _connect(self):
        """Establish connection to Roboflow."""
        api_key = self.config.get('api_key', '').strip()
        workspace_id = self.config.get('workspace_id', '').strip()
        project_id = self.config.get('project_id', '').strip()

        if not api_key or not workspace_id or not project_id:
            self.report_error("Roboflow API Key, Workspace ID, and Project ID are all required")
            return

        try:
            from roboflow import Roboflow
        except ImportError:
            self.report_error("roboflow package not installed. Install with: pip install roboflow")
            return

        try:
            rf = Roboflow(api_key=api_key)
            workspace = rf.workspace(workspace_id)
            self._rf_project = workspace.project(project_id)
            print(f"[RoboflowUploadNode] Connected to {workspace_id}/{project_id}")
        except Exception as e:
            self.report_error(f"Roboflow connection failed: {e}")
            self._rf_project = None

    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Decode image from message and upload to Roboflow."""
        if not self._rf_project:
            self.report_error("Not connected to Roboflow (check configuration)")
            self.send(msg)
            return

        # Rate limiting
        rate_limit = self.get_config_float('rate_limit', 0)
        if rate_limit > 0:
            import time
            now = time.time()
            with self._lock:
                if now - self._last_upload_time < rate_limit:
                    self.send(msg)
                    return
                self._last_upload_time = now

        # Extract and decode image
        payload = msg.get(MessageKeys.PAYLOAD)
        if payload is None:
            self.report_error("No payload in message")
            self.send(msg)
            return

        image, _ = self.decode_image(payload)
        if image is None:
            self.report_error("Could not decode image from message payload")
            self.send(msg)
            return

        # Encode to JPEG and write to a temp file (Roboflow SDK requires a file path)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')[:-3]
        filename = f"pynode_{timestamp}.jpg"
        temp_path = os.path.join(tempfile.gettempdir(), filename)

        try:
            success, buffer = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not success:
                self.report_error("Failed to encode image as JPEG")
                self.send(msg)
                return

            with open(temp_path, 'wb') as f:
                f.write(buffer.tobytes())

            batch_name = self.config.get('batch_name', '').strip() or None
            self._rf_project.upload(temp_path, batch_name=batch_name)

        except Exception as e:
            self.report_error(f"Roboflow upload failed: {e}")
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

        self.send(msg)
