"""
Node implementations for the PyNode workflow system.
"""

from .InjectNode.inject_node import InjectNode
from .FunctionNode.function_node import FunctionNode
from .DebugNode.debug_node import DebugNode
from .ChangeNode.change_node import ChangeNode
from .SwitchNode.switch_node import SwitchNode
from .DelayNode.delay_node import DelayNode
from .MqttInNode.mqtt_in_node import MqttInNode
from .MqttOutNode.mqtt_out_node import MqttOutNode
from .CameraNode.camera_node import CameraNode
from .ImageViewerNode.image_viewer_node import ImageViewerNode
from .GateNode.gate_node import GateNode
from .UltralyticsNode.ultralytics_node import UltralyticsNode
from .TemplateNode.template_node import TemplateNode


def get_all_node_types():
    """
    Get a list of all available node types.
    
    Returns:
        List of node classes
    """
    return [
        InjectNode,
        FunctionNode,
        DebugNode,
        ChangeNode,
        SwitchNode,
        DelayNode,
        MqttInNode,
        MqttOutNode,
        CameraNode,
        ImageViewerNode,
        GateNode,
        UltralyticsNode,
        TemplateNode
    ]

__all__ = [
    'InjectNode',
    'FunctionNode',
    'DebugNode',
    'ChangeNode',
    'SwitchNode',
    'DelayNode',
    'MqttInNode',
    'MqttOutNode',
    'CameraNode',
    'ImageViewerNode',
    'GateNode',
    'UltralyticsNode',
    'TemplateNode'
]
