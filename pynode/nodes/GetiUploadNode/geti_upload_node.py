"""
Geti Upload Node - uploads images to an Intel Geti platform project for annotation.
"""

import base64
import threading
from typing import Any, Dict, Optional
import numpy as np
import cv2

from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Uploads images to an Intel Geti platform project for annotation and training.")
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
    ("Host:", "URL of the Geti server (e.g. https://geti.example.com)."),
    ("Token:", "Personal access token from the Geti user menu."),
    ("Project Name:", "Name of the target project (or use Project ID)."),
    ("Project ID:", "UUID of the target project (or use Project Name)."),
    ("Dataset Name:", "Optional dataset within the project. Uses the training dataset if empty."),
    ("Verify SSL:", "Whether to verify SSL certificates for HTTPS connections."),
    ("Rate Limit:", "Minimum seconds between uploads (0 = no limit).")
)
_info.add_header("Notes")
_info.add_text("Requires the geti-sdk package. The node connects to Geti when the workflow starts and disconnects when it stops.")


class GetiUploadNode(BaseNode):
    """Uploads images to Intel Geti for annotation."""

    display_name = 'Geti Upload'
    icon = '\u2B06'
    category = 'output'
    color = '#4A90D9'
    border_color = '#2E6BB0'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    info = str(_info)

    DEFAULT_CONFIG = {
        'host': '',
        'token': '',
        'project_name': '',
        'project_id': '',
        'dataset_name': '',
        'verify_certificate': False,
        'rate_limit': 0,
        MessageKeys.DROP_MESSAGES: True
    }

    properties = [
        {
            'name': 'host',
            'label': 'Geti Server Host',
            'type': 'text',
            'default': '',
            'placeholder': 'https://your_geti_server.com',
            'help': 'URL or IP address of the Geti server'
        },
        {
            'name': 'token',
            'label': 'Personal Access Token',
            'type': 'text',
            'default': '',
            'placeholder': 'Your Geti personal access token',
            'help': 'Personal access token from Geti user menu'
        },
        {
            'name': 'project_name',
            'label': 'Project Name',
            'type': 'text',
            'default': '',
            'placeholder': 'e.g. my-detection-project',
            'help': 'Name of the Geti project (use this or Project ID)'
        },
        {
            'name': 'project_id',
            'label': 'Project ID',
            'type': 'text',
            'default': '',
            'placeholder': 'e.g. 12345678-1234-...',
            'help': 'UUID of the Geti project (use this or Project Name)'
        },
        {
            'name': 'dataset_name',
            'label': 'Dataset Name',
            'type': 'text',
            'default': '',
            'placeholder': 'e.g. inference-data',
            'help': 'Dataset within the project (optional, uses training dataset if empty)'
        },
        {
            'name': 'verify_certificate',
            'label': 'Verify SSL Certificate',
            'type': 'checkbox',
            'default': False,
            'help': 'Verify SSL certificates for HTTPS connections'
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

    def __init__(self, node_id=None, name="geti upload"):
        super().__init__(node_id, name)
        self._geti_client = None
        self._image_client = None
        self._project = None
        self._dataset = None
        self._last_upload_time = 0.0
        self._lock = threading.Lock()

    def on_start(self):
        """Connect to Geti when the workflow starts."""
        super().on_start()
        self._connect()

    def on_stop(self):
        """Disconnect from Geti when the workflow stops."""
        self._disconnect()
        super().on_stop()

    def configure(self, config: Dict[str, Any]):
        """Reconnect if configuration changes while running."""
        super().configure(config)

    def _connect(self):
        """Establish connection to the Geti platform."""
        host = self.config.get('host', '').strip()
        token = self.config.get('token', '').strip()
        project_name = self.config.get('project_name', '').strip()
        project_id = self.config.get('project_id', '').strip()
        dataset_name = self.config.get('dataset_name', '').strip()
        verify_cert = self.get_config_bool('verify_certificate', False)

        if not host or not token:
            self.report_error("Geti host and token are required")
            return

        if not project_name and not project_id:
            self.report_error("Either Project Name or Project ID must be specified")
            return

        try:
            from geti_sdk import Geti
            from geti_sdk.rest_clients import ProjectClient, ImageClient, DatasetClient
        except ImportError:
            self.report_error("geti-sdk package not installed. Install with: pip install geti-sdk")
            return

        try:
            self._geti_client = Geti(
                host=host,
                token=token,
                verify_certificate=verify_cert
            )

            project_client = ProjectClient(
                session=self._geti_client.session,
                workspace_id=self._geti_client.workspace_id
            )

            # Find project by name or ID
            if project_name:
                self._project = project_client.get_project_by_name(project_name)
            else:
                self._project = project_client.get_project_by_id(project_id)

            if self._project is None:
                self.report_error("Could not find the specified Geti project")
                return

            self._image_client = ImageClient(
                session=self._geti_client.session,
                workspace_id=self._geti_client.workspace_id,
                project=self._project
            )

            # Resolve dataset if specified
            self._dataset = None
            if dataset_name:
                try:
                    dataset_client = DatasetClient(
                        session=self._geti_client.session,
                        workspace_id=self._geti_client.workspace_id,
                        project=self._project
                    )
                    self._dataset = dataset_client.get_dataset_by_name(dataset_name)
                except Exception as e:
                    self.report_error(f"Dataset '{dataset_name}' not found, using training dataset: {e}")

            proj_label = getattr(self._project, 'name', None) or project_id
            print(f"[GetiUploadNode] Connected to {host} -> {proj_label}")

        except Exception as e:
            self.report_error(f"Geti connection failed: {e}")
            self._geti_client = None
            self._image_client = None
            self._project = None

    def _disconnect(self):
        """Close the Geti connection."""
        if self._geti_client:
            try:
                self._geti_client.logout()
            except Exception:
                pass
            finally:
                self._geti_client = None
                self._image_client = None
                self._project = None
                self._dataset = None

    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Decode image from message and upload to Geti."""
        if not self._image_client or not self._project:
            self.report_error("Not connected to Geti (check configuration)")
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

        # Upload
        try:
            self._image_client.upload_image(
                image=image,
                dataset=self._dataset
            )
        except Exception as e:
            self.report_error(f"Geti upload failed: {e}")

        self.send(msg)
