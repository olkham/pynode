"""UDP Out node - sends messages to a UDP listener using the PNB1 protocol.

The listener can be a PyNode ``UdpInNode``, or any external program that
implements the PNB1 wire format (see ``udp_protocol.py``) - e.g. the example
Node-RED flow in ``interop/``.
"""

import json
import socket
from typing import Any, Dict

from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.SocketNode import udp_protocol

_info = Info()
_info.add_text(
    "Sends each incoming message to a remote UDP listener using the PNB1 "
    "protocol - a lightweight, chunked, stdlib-only wire format for moving "
    "messages (including video frames) over UDP to another PyNode instance "
    "or any program that implements it.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Any message. msg.payload is encoded and sent; msg.topic is "
                 "included in the datagram metadata."),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Host:", "Destination host running the paired listener (a UdpInNode or "
              "any PNB1-speaking UDP receiver)."),
    ("Port:", "Destination UDP port."),
    ("Chunk Size:", "Body bytes per datagram. 60000 (default) is fastest on "
                    "a LAN; 1400 keeps every datagram under a single MTU for "
                    "WAN/VPN links. Chunk size only affects fragmentation, "
                    "not decoding, so a mismatch between ends just changes "
                    "how many datagrams a message takes, not whether it can "
                    "be decoded."),
    ("Encode Images:", "When on (default), numpy image arrays are JPEG "
                       "encoded before sending (a 1080p BGR frame is ~6MB "
                       "raw vs ~100-300KB as JPEG). When off, images are "
                       "sent as raw bytes with dtype/shape metadata - only "
                       "useful for PyNode-to-PyNode, since a non-Python "
                       "receiver has no numpy to reshape them with."),
    ("Include Extra Message Properties:", "When on, forwards EVERY msg "
                       "property other than payload/topic (including "
                       "underscore ones: _msgid, _timestamp_orig, "
                       "_timestamp_emit, _age, _queue_length, drop_count, "
                       "and any custom fields) in the datagram metadata's "
                       "'extra' object, so the receiver reconstructs the "
                       "message exactly. Properties whose values are not "
                       "JSON-serializable are skipped individually."),
)
_info.add_header("Protocol")
_info.add_text(
    "See pynode/nodes/SocketNode/udp_protocol.py for the full wire format, "
    "and pynode/nodes/SocketNode/interop/ for a standalone udp_probe.py "
    "diagnostic and an example Node-RED flow that implements it.")
_info.add_header("Notes")
_info.add_bullets(
    ("UDP is unreliable:", "datagrams can be lost, duplicated, or reordered. "
                           "These nodes do not retransmit or acknowledge - "
                           "they are designed for loopback/LAN use (telemetry, "
                           "video preview, control messages) where an "
                           "occasional dropped frame is acceptable. For "
                           "guaranteed delivery use the TCP Out node."),
    ("No encryption or authentication:", "anyone who can reach the port can "
                       "send/receive. Do not expose it directly to an "
                       "untrusted network."),
)


class UdpOutNode(BaseNode):
    """Sends messages to a remote UDP listener using the PNB1 protocol."""

    info = str(_info)
    display_name = 'UDP Out'
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
        'chunk_size': str(udp_protocol.DEFAULT_CHUNK_SIZE),
        'encode_images': True,
        'include_msg_props': False,
    }

    properties = [
        {
            'name': 'host',
            'label': 'Host',
            'type': 'text',
            'default': DEFAULT_CONFIG['host'],
            'help': "Destination host running the paired UDP In node (or any PNB1-speaking UDP listener)"
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
                {'value': str(udp_protocol.DEFAULT_CHUNK_SIZE),
                 'label': f'{udp_protocol.DEFAULT_CHUNK_SIZE} bytes (fast LAN, default)'},
                {'value': str(udp_protocol.MTU_CHUNK_SIZE),
                 'label': f'{udp_protocol.MTU_CHUNK_SIZE} bytes (MTU-safe WAN)'}
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
            'help': 'Forward every msg property besides payload/topic (incl. _msgid, timestamps, ...) so the receiver replicates the message exactly'
        },
    ]

    def __init__(self, node_id=None, name="udp out"):
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
            self.report_error("UDP Out: UDP socket not open (node not started)")
            return

        host = str(self.config.get('host', self.DEFAULT_CONFIG['host']))
        port = self.get_config_int('port', self.DEFAULT_CONFIG['port'])
        chunk_size = self.get_config_int('chunk_size', udp_protocol.DEFAULT_CHUNK_SIZE)
        encode_images = self.get_config_bool('encode_images', True)
        include_props = self.get_config_bool('include_msg_props', False)

        topic = msg.get(MessageKeys.TOPIC, '') or ''
        payload = msg.get(MessageKeys.PAYLOAD)

        extra_props = None
        if include_props:
            # Forward the WHOLE message (except payload/topic, which travel in
            # dedicated fields and are restored on arrival) - underscore props
            # included - so the receiver can replicate the message exactly.
            # Filter per-key for JSON-serializability so one exotic value
            # (e.g. a numpy array stashed at a custom key) skips that key
            # instead of failing the whole message.
            reserved = {MessageKeys.PAYLOAD, MessageKeys.TOPIC}
            extra_props = {}
            for k, v in msg.items():
                if k in reserved:
                    continue
                try:
                    json.dumps(v)
                except (TypeError, ValueError):
                    continue
                extra_props[k] = v

        self._message_id = udp_protocol.next_message_id(self._message_id)

        try:
            datagrams = udp_protocol.build_datagrams(
                self._message_id, topic, payload,
                extra_props=extra_props,
                chunk_size=chunk_size,
                encode_images=encode_images,
            )
        except udp_protocol.EncodeError as e:
            self.error_count += 1
            self.report_error(f"UDP Out: failed to encode message: {e}")
            return

        # One report_error per burst (this message), not per datagram - a
        # socket error is very likely to repeat for every remaining chunk,
        # so stop sending the rest of this message and report once.
        try:
            for datagram in datagrams:
                self._socket.sendto(datagram, (host, port))
        except OSError as e:
            self.error_count += 1
            self.report_error(f"UDP Out: UDP send to {host}:{port} failed: {e}")
            return

        self.sent_count += 1
