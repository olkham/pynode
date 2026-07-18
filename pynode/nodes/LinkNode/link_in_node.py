"""
Link In node - receives messages published to a named channel on the
process-wide Link bus (by Link Out nodes, possibly in another flow) and emits
them from its output.
"""

from typing import Any, Dict, Optional
from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.LinkNode.link_bus import link_bus

_info = Info()
_info.add_text(
    "Receives messages published on a named channel by Link Out nodes and "
    "emits them from its output. The Link Out may live in a different "
    "flow/workflow, so this is how you feed a source in one flow into another.")
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Each message published to the configured channel (a deep "
                  "copy, isolated from the sending flow).")
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Channel:", "The channel name to listen on. Must match the Channel of "
                 "the Link Out node(s) sending to it. Leave empty to disable."),
)
_info.add_header("Behavior")
_info.add_bullets(
    ("Deploy-scoped:", "Only registers to receive while the flow is deployed "
                       "and running; stopping or disabling the node stops "
                       "delivery."),
    ("Fan-in/out:", "Multiple Link In nodes on one channel all receive; "
                    "multiple Link Out nodes on one channel all feed in."),
)


class LinkInNode(BaseNode):
    """Receive messages from a named channel on the Link bus."""

    display_name = 'Link In'
    icon = '⇤'
    category = 'common'
    color = '#B0BEC5'
    border_color = '#78909C'
    text_color = '#000000'
    input_count = 0
    output_count = 1
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
    }

    properties = [
        {
            'name': 'channel',
            'label': 'Channel',
            'type': 'link-channel',
            'default': '',
            'placeholder': 'e.g. camera-feed',
            'help': 'Listen for messages published to this channel by Link Out '
                    'nodes.'
        }
    ]

    def __init__(self, node_id=None, name="link in"):
        super().__init__(node_id, name)
        # Channel this node is currently registered under (None = not
        # registered). Tracked so on_stop always unregisters from the exact
        # channel that on_start registered, even if the config changed since.
        self._registered_channel: Optional[str] = None

    def receive(self, msg: Dict[str, Any]):
        """Called by the Link bus when a message arrives on our channel.

        Routes the message through BaseNode.send, which deep-copies it for each
        downstream connection - isolating this flow from the publishing flow.
        """
        self.send(msg)

    def on_start(self):
        """Register with the Link bus so published messages are delivered."""
        super().on_start()
        channel = str(self.config.get('channel', '')).strip()
        self._registered_channel = channel or None
        link_bus.register(channel, self)

    def on_stop(self):
        """Unregister from the Link bus so no further messages are delivered."""
        if self._registered_channel is not None:
            link_bus.unregister(self._registered_channel, self)
            self._registered_channel = None
        super().on_stop()

    def on_close(self):
        """Cleanup when the node is deleted."""
        self.on_stop()
