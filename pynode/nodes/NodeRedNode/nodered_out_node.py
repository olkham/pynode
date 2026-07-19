"""Node-RED Out node - sends messages to a UDP listener (Node-RED or another
PyNode instance) using the PNB1 bridge protocol.
"""

import socket
from typing import Any, Dict

from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.NodeRedNode import bridge_protocol

_info = Info()
_info.add_text(
    "Sends each incoming message to a remote UDP listener using the PNB1 "
    "bridge protocol - a lightweight, chunked, stdlib-only wire format "
    "designed to move messages (including video frames) between PyNode and "
    "Node-RED, or between two PyNode instances, over UDP.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Any message. msg.payload is encoded and sent; msg.topic is "
                 "included in the datagram metadata."),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Host:", "Destination host running the paired listener (Node-RED's "
              "'udp in' node, or a NodeRedInNode)."),
    ("Port:", "Destination UDP port."),
    ("Chunk Size:", "Body bytes per datagram. 60000 (default) is fastest on "
                    "a LAN; 1400 keeps every datagram under a single MTU for "
                    "WAN/VPN links. Must match on both ends of the bridge - "
                    "chunk size only affects fragmentation, not decoding, so "
                    "a mismatch just changes how many datagrams a message "
                    "takes, not whether it can be decoded."),
    ("Encode Images:", "When on (default), numpy image arrays are JPEG "
                       "encoded before sending (a 1080p BGR frame is ~6MB "
                       "raw vs ~100-300KB as JPEG). When off, images are "
                       "sent as raw bytes with dtype/shape metadata - only "
                       "useful for PyNode-to-PyNode, since Node-RED has no "
                       "numpy to reshape them with."),
    ("Include Extra Message Properties:", "When on, forwards every "
                       "non-underscore msg property other than payload/topic "
                       "(e.g. a custom field added upstream) in the datagram "
                       "metadata's 'extra' object, so a receiving "
                       "NodeRedInNode can restore them onto the emitted "
                       "message."),
)
_info.add_header("Protocol")
_info.add_text(
    "See pynode/nodes/NodeRedNode/bridge_protocol.py for the full wire "
    "format, and pynode/nodes/NodeRedNode/nodered/ for a ready-to-import "
    "Node-RED flow (pynode-bridge-flow.json) implementing both directions "
    "with core nodes only.")
_info.add_header("Notes")
_info.add_bullets(
    ("UDP is unreliable:", "datagrams can be lost, duplicated, or reordered. "
                           "This bridge does not retransmit or acknowledge - "
                           "it is designed for loopback/LAN use (telemetry, "
                           "video preview, control messages) where an "
                           "occasional dropped frame is acceptable."),
    ("No encryption or authentication:", "anyone who can reach the port can "
                       "send/receive. Do not expose it directly to an "
                       "untrusted network."),
)


class NodeRedOutNode(BaseNode):
    """Sends messages to a remote UDP listener using the PNB1 bridge protocol."""

    info = str(_info)
    display_name = 'Node-RED Out'
    icon = '📡'
    category = 'network'
    color = '#87A980'
    border_color = '#5F7858'
    text_color = '#000000'
    input_count = 1
    output_count = 0

    DEFAULT_CONFIG = {
        'host': '127.0.0.1',
        'port': 7401,
        'chunk_size': str(bridge_protocol.DEFAULT_CHUNK_SIZE),
        'encode_images': True,
        'include_msg_props': False,
    }

    properties = [
        {
            'name': 'host',
            'label': 'Host',
            'type': 'text',
            'default': DEFAULT_CONFIG['host'],
            'help': "Destination host running Node-RED's udp-in node (or another PyNode's Node-RED In node)"
        },
        {
            'name': 'port',
            'label': 'Port',
            'type': 'number',
            'default': DEFAULT_CONFIG['port'],
            'help': 'Destination UDP port'
        },
        {
            'name': 'chunk_size',
            'label': 'Chunk Size',
            'type': 'select',
            'options': [
                {'value': str(bridge_protocol.DEFAULT_CHUNK_SIZE),
                 'label': f'{bridge_protocol.DEFAULT_CHUNK_SIZE} bytes (fast LAN, default)'},
                {'value': str(bridge_protocol.MTU_CHUNK_SIZE),
                 'label': f'{bridge_protocol.MTU_CHUNK_SIZE} bytes (MTU-safe WAN)'}
            ],
            'default': DEFAULT_CONFIG['chunk_size'],
            'help': 'Body bytes per UDP datagram. Must be a value the receiver can reassemble (any value works, this just controls fragmentation).'
        },
        {
            'name': 'encode_images',
            'label': 'Encode Images as JPEG',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['encode_images'],
            'help': 'JPEG-encode numpy image payloads before sending (recommended - raw 1080p frames are ~6MB)'
        },
        {
            'name': 'include_msg_props',
            'label': 'Include Extra Message Properties',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['include_msg_props'],
            'help': 'Forward non-underscore extra msg properties (besides payload/topic) in the datagram metadata'
        },
    ]

    def __init__(self, node_id=None, name="node-red out"):
        super().__init__(node_id, name)
        self._socket = None
        self._message_id = 0
        self.sent_count = 0
        self.error_count = 0

    # OS send buffer (SO_SNDBUF): a burst of large datagrams (e.g. a ~6MB
    # 1080p frame fragmented into ~100 x 60KB chunks) written back to back
    # with no pacing can fill a small default send buffer, so enlarge it -
    # best-effort, some platforms cap or ignore this.
    _SEND_SOCKET_BUFFER_SIZE = 4 * 1024 * 1024

    def on_start(self):
        super().on_start()
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self._SEND_SOCKET_BUFFER_SIZE)
            except OSError:
                pass
        except OSError as e:
            self.report_error(f"Failed to create UDP socket: {e}")
            self._socket = None

    def on_stop(self):
        super().on_stop()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def on_close(self):
        """Cleanup when node is removed."""
        self.on_stop()

    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        if not self._socket:
            self.report_error("Node-RED Out: UDP socket not open (node not started)")
            return

        host = str(self.config.get('host', self.DEFAULT_CONFIG['host']))
        port = self.get_config_int('port', self.DEFAULT_CONFIG['port'])
        chunk_size = self.get_config_int('chunk_size', bridge_protocol.DEFAULT_CHUNK_SIZE)
        encode_images = self.get_config_bool('encode_images', True)
        include_props = self.get_config_bool('include_msg_props', False)

        topic = msg.get(MessageKeys.TOPIC, '') or ''
        payload = msg.get(MessageKeys.PAYLOAD)

        extra_props = None
        if include_props:
            reserved = {MessageKeys.PAYLOAD, MessageKeys.TOPIC}
            extra_props = {
                k: v for k, v in msg.items()
                if k not in reserved and not k.startswith('_')
            }

        self._message_id = bridge_protocol.next_message_id(self._message_id)

        try:
            datagrams = bridge_protocol.build_datagrams(
                self._message_id, topic, payload,
                extra_props=extra_props,
                chunk_size=chunk_size,
                encode_images=encode_images,
            )
        except bridge_protocol.EncodeError as e:
            self.error_count += 1
            self.report_error(f"Node-RED Out: failed to encode message: {e}")
            return

        # One report_error per burst (this message), not per datagram - a
        # socket error is very likely to repeat for every remaining chunk,
        # so stop sending the rest of this message and report once.
        try:
            for datagram in datagrams:
                self._socket.sendto(datagram, (host, port))
        except OSError as e:
            self.error_count += 1
            self.report_error(f"Node-RED Out: UDP send to {host}:{port} failed: {e}")
            return

        self.sent_count += 1
