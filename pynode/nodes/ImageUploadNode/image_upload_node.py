"""
Image Upload Node - accepts image uploads via drag-and-drop on the node.
Sends the uploaded image downstream as a message.
"""

import base64
import numpy as np
import cv2
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Accepts image files via drag-and-drop onto the node. "
               "The uploaded image is sent downstream as a message.")
_info.add_header("Usage")
_info.add_bullets(
    "Drag and drop an image file onto the node in the editor.",
    "Supported formats: JPEG, PNG, BMP, TIFF, WebP.",
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Message with the uploaded image in payload."),
)


class ImageUploadNode(BaseNode):
    """Receives image uploads and sends them downstream."""

    display_name = 'Image Upload'
    icon = '📤'
    category = 'input'
    color = '#C0DEED'
    border_color = '#87A9C1'
    text_color = '#000000'
    input_count = 0
    output_count = 1
    info = str(_info)

    ui_component = 'image-drop'
    ui_component_config = {
        'tooltip': 'Drop an image here',
    }

    properties = []

    def __init__(self, node_id=None, name="image upload"):
        super().__init__(node_id, name)

    def receive_image(self, image_bytes: bytes, filename: str = ""):
        """
        Called by the server when an image is uploaded to this node.

        Args:
            image_bytes: Raw image file bytes.
            filename: Original filename of the uploaded image.
        """
        # Decode image bytes to numpy array
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is None:
            self.report_error(f"Failed to decode uploaded image: {filename}")
            return

        # Encode as JPEG base64 for the standard image message format
        ret, buffer = cv2.imencode('.jpg', image)
        if not ret:
            self.report_error("Failed to encode uploaded image as JPEG")
            return

        jpeg_base64 = base64.b64encode(buffer.tobytes()).decode('utf-8')

        msg = self.create_message(payload={
            'image': {
                'format': 'jpeg',
                'encoding': 'base64',
                'data': jpeg_base64,
                'width': image.shape[1],
                'height': image.shape[0],
            },
            'filename': filename,
        })
        self.send(msg)
