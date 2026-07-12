"""Message key definitions and message helpers shared by all nodes.

Extracted from ``base_node.py``; ``pynode.nodes.base_node`` re-exports
``MessageKeys`` and ``sort_msg_keys`` so existing imports keep working.
"""

from dataclasses import dataclass
from typing import Any, Dict


def sort_msg_keys(msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sort message dict with underscore keys first, then alphabetically.
    Useful for displaying debug messages with metadata fields first.

    Args:
        msg: Message dictionary to sort

    Returns:
        New dictionary with sorted keys
    """
    return dict(sorted(msg.items(), key=lambda x: (not x[0].startswith('_'), x[0])))


#Message key definitions to standardize message strings across all nodes
@dataclass(frozen=True)
class MessageKeys:

    # Image-specific keys
    @dataclass(frozen=True)
    class IMAGE:
        PATH: str = 'image'
        FORMAT: str = 'format'
        ENCODING: str = 'encoding'
        DATA: str = 'data'
        WIDTH: str = 'width'
        HEIGHT: str = 'height'
        JPEG_QUALITY: str = 'jpeg_quality'
        ENCODE_JPEG: str = 'encode_jpeg'

    # Camera-specific keys
    @dataclass(frozen=True)
    class CAMERA:
        DEVICE_INDEX: str = 'device_index'
        SOURCE: str = 'source'
        SOURCE_TYPE: str = 'source_type'
        FPS: str = 'fps'
        WIDTH: str = 'width'
        HEIGHT: str = 'height'
        JPEG_QUALITY: str = 'jpeg_quality'
        ENCODE_JPEG: str = 'encode_jpeg'

    class VIDEO:
        LOOP: str = 'loop'
        SOURCE: str = 'source'

    class CV:
        BBOX: str = 'bbox'
        BBOX_FORMAT: str = 'bbox_format'
        CONFIDENCE: str = 'confidence'
        CLASS_ID: str = 'class_id'
        CLASS_NAME: str = 'class_name'
        DETECTIONS: str = 'detections'
        DETECTION_COUNT: str = 'detection_count'
        TRACK_ID: str = 'track_id'
        MASK: str = 'mask'
        SEGMENTATION: str = 'segmentation'
        THRESHOLD: str = 'threshold'

    # Message-level keys
    MSG = 'msg'
    MSG_ID: str = '_msgid'
    ORIGINAL_MSG: str = '_original_msg'
    TIMESTAMP_ORIG: str = '_timestamp_orig'
    TIMESTAMP_EMIT: str = '_timestamp_emit'
    AGE: str = '_age'
    DROP_COUNT: str = 'drop_count'
    DROP_MESSAGES: str = 'drop_messages'
    PAYLOAD: str = 'payload'
    TOPIC: str = 'topic'
    QUEUE_LENGTH: str = '_queue_length'
