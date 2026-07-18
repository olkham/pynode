"""
Link Out node - publishes messages to a named channel on the process-wide
Link bus, so they can be received by Link In nodes anywhere (including in a
different workflow/flow).
"""

from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.LinkNode.link_bus import link_bus

_info = Info()
_info.add_text(
    "Publishes each incoming message to a named channel on the Link bus. "
    "Every Link In node configured with the same channel receives a copy - "
    "including nodes in other flows/workflows. Use it to wire a source (e.g. "
    "a camera feed) in one flow to consumers in another without a visible "
    "connection.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Any message. It is forwarded unchanged to the channel.")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Channel:", "The channel name to publish on. Must match the Channel of "
                 "the Link In node(s) that should receive the message. Leave "
                 "empty to disable publishing."),
)
_info.add_header("Usage")
_info.add_bullets(
    ("Cross-flow:", "Put a Link Out in Flow 1 and a Link In with the same "
                    "channel in Flow 2."),
    ("Isolation:", "Each receiver gets a deep copy, so flows never mutate each "
                   "other's messages."),
    ("Loops:", "A Link Out and Link In on the same channel in one flow form a "
               "cycle - avoid this (same as Node-RED link nodes)."),
)


class LinkOutNode(BaseNode):
    """Publish messages to a named channel on the Link bus."""

    display_name = 'Link Out'
    icon = '⇥'
    category = 'common'
    color = '#B0BEC5'
    border_color = '#78909C'
    text_color = '#000000'
    input_count = 1
    output_count = 0
    info = str(_info)

    # Show the channel on the node card (right side).
    ui_component = 'config-badge'
    ui_component_config = {
        'key': 'channel',
        'prefix': '# ',
        'placeholder': '(no channel)',
    }

    DEFAULT_CONFIG = {
        'channel': '',
        # Link Out just fans a message out to the bus (cheap), so forward
        # reliably rather than dropping when momentarily busy. Backpressure /
        # dropping is the responsibility of consumer nodes in the target flow.
        MessageKeys.DROP_MESSAGES: 'false',
    }

    properties = [
        {
            'name': 'channel',
            'label': 'Channel',
            'type': 'link-channel',
            'default': '',
            'placeholder': 'e.g. camera-feed',
            'help': 'Publish messages to this channel. Link In nodes with the '
                    'same channel receive them.'
        }
    ]

    def __init__(self, node_id=None, name="link out"):
        super().__init__(node_id, name)

    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Publish the message to the configured channel."""
        channel = str(self.config.get('channel', '')).strip()
        if not channel:
            return
        link_bus.publish(channel, msg)
