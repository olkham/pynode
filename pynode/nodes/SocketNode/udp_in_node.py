"""UDP In node - receives messages from a remote UDP sender using the PNB1
protocol.

The sender can be a PyNode ``UdpOutNode``, or any external program that
implements the PNB1 wire format (see ``udp_protocol.py``) - e.g. the example
Node-RED flow in ``interop/``.
"""

import socket
import threading
import time
from typing import Any, Dict

from pynode.nodes.base_node import BaseNode, Info, MessageKeys
from pynode.nodes.SocketNode import udp_protocol

_info = Info()
_info.add_text(
    "Listens on a UDP port for messages sent using the PNB1 protocol - a "
    "lightweight, chunked, stdlib-only wire format for moving messages "
    "(including video frames) over UDP from another PyNode instance or any "
    "program that implements it. Fragmented messages are reassembled before "
    "being emitted.")
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "One message per completed datagram sequence received. "
                  "msg.payload is decoded per the sender's metadata (JSON "
                  "object, raw bytes, a numpy image, or a raw numpy array); "
                  "msg.topic is set from the sender's topic if present."),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Bind Host:", "Local address to listen on. '0.0.0.0' (default) accepts "
                   "from any interface; use '127.0.0.1' to restrict to "
                   "loopback-only senders."),
    ("Port:", "Local UDP port to listen on. Must match the sending side's "
              "configured destination port."),
    ("Reassembly Timeout (s):", "How long to keep a partially-received "
                       "message's chunks before giving up on it (default "
                       "2s). A message that never fully arrives (dropped "
                       "chunk) is silently discarded after this timeout - "
                       "it is never emitted."),
)
_info.add_header("Protocol")
_info.add_text(
    "See pynode/nodes/SocketNode/udp_protocol.py for the full wire format, "
    "and pynode/nodes/SocketNode/interop/ for a standalone udp_probe.py "
    "diagnostic and an example Node-RED flow that implements it.")
_info.add_header("Notes")
_info.add_bullets(
    ("UDP is unreliable:", "datagrams can be lost, duplicated, or reordered. "
                           "A message with a missing chunk is dropped (not "
                           "emitted) after the reassembly timeout - there is "
                           "no retransmission. Intended for loopback/LAN use."),
    ("No encryption or authentication:", "anyone who can reach the port can "
                       "send to it. Do not expose it directly to an "
                       "untrusted network."),
)


class UdpInNode(BaseNode):
    """Receives messages from a remote UDP sender using the PNB1 protocol."""

    info = str(_info)
    display_name = 'UDP In'
    icon = '📡'
    category = 'network'
    color = '#87A980'
    border_color = '#5F7858'
    text_color = '#000000'
    input_count = 0
    output_count = 1

    DEFAULT_CONFIG = {
        'bind_host': '0.0.0.0',
        'port': 7401,
        'reassembly_timeout': udp_protocol.DEFAULT_REASSEMBLY_TIMEOUT,
    }

    properties = [
        {
            'name': 'bind_host',
            'label': 'Bind Host',
            'type': 'text',
            'default': DEFAULT_CONFIG['bind_host'],
            'help': "Local address to listen on ('0.0.0.0' = all interfaces, '127.0.0.1' = loopback only)"
        },
        {
            'name': 'port',
            'label': 'Port',
            'type': 'number',
            'default': DEFAULT_CONFIG['port'],
            'help': "Local UDP port to listen on"
        },
        {
            'name': 'reassembly_timeout',
            'label': 'Reassembly Timeout (s)',
            'type': 'number',
            'default': DEFAULT_CONFIG['reassembly_timeout'],
            'help': 'Seconds to wait for all chunks of a message before dropping it'
        },
    ]

    # Poll interval for the socket's recv timeout (bounds shutdown latency)
    # and how often the background thread sweeps for stale reassembly
    # buffers while idle.
    _SOCKET_POLL_TIMEOUT = 0.5
    _EVICT_INTERVAL = 0.5
    _RECV_BUFFER_SIZE = 65535
    # OS socket receive buffer (SO_RCVBUF), not to be confused with
    # _RECV_BUFFER_SIZE above (the per-recvfrom() userspace read size). See
    # the comment in on_start() for why this needs to be generous.
    _RECV_SOCKET_BUFFER_SIZE = 4 * 1024 * 1024

    def __init__(self, node_id=None, name="udp in"):
        super().__init__(node_id, name)
        self._socket = None
        self._recv_thread = None
        self._stop_flag = threading.Event()
        self._reassembler = None
        self.bound_port = None  # actual bound port (useful when port=0 in tests)
        self.received_count = 0
        self.error_count = 0

    def on_start(self):
        super().on_start()

        bind_host = str(self.config.get('bind_host', self.DEFAULT_CONFIG['bind_host']))
        port = self.get_config_int('port', self.DEFAULT_CONFIG['port'])
        timeout = self.get_config_float('reassembly_timeout', udp_protocol.DEFAULT_REASSEMBLY_TIMEOUT)

        self._reassembler = udp_protocol.Reassembler(timeout=timeout)

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Enlarge the receive buffer: a burst of large datagrams (e.g. a
            # ~6MB 1080p frame fragmented into ~100 x 60KB chunks, sent back
            # to back with no pacing) can arrive faster than this thread
            # drains recvfrom() calls. The OS default SO_RCVBUF is often too
            # small to hold more than one or two such datagrams, silently
            # dropping the rest before they're ever read. Best-effort: some
            # platforms cap or ignore this, which just means falling back to
            # the OS default.
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self._RECV_SOCKET_BUFFER_SIZE)
            except OSError:
                pass
            sock.bind((bind_host, port))
            sock.settimeout(self._SOCKET_POLL_TIMEOUT)
        except OSError as e:
            self.report_error(f"UDP In: failed to bind UDP socket on {bind_host}:{port}: {e}")
            return

        self._socket = sock
        self.bound_port = sock.getsockname()[1]

        self._stop_flag.clear()
        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()

    def on_stop(self):
        self._stop_flag.set()
        if self._recv_thread and self._recv_thread.is_alive():
            self._recv_thread.join(timeout=2.0)
        self._recv_thread = None

        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

        super().on_stop()

    def on_close(self):
        """Cleanup when node is removed."""
        self.on_stop()

    def _receive_loop(self):
        """Background receiver: recvfrom loop with a socket timeout so it can
        poll ``_stop_flag`` periodically instead of blocking forever, plus a
        periodic sweep for reassembly buffers that never completed.
        """
        last_evict = time.monotonic()
        while not self._stop_flag.is_set():
            try:
                data, addr = self._socket.recvfrom(self._RECV_BUFFER_SIZE)
            except socket.timeout:
                data = None
            except OSError:
                # Socket closed out from under us (on_stop) or a transient
                # error - either way, stop looping rather than spin.
                break

            if data:
                try:
                    result = self._reassembler.add_datagram(addr, data)
                except Exception as e:  # pragma: no cover - defensive
                    self.error_count += 1
                    self.report_error(f"UDP In: error reassembling datagram from {addr}: {e}")
                    result = None
                if result is not None:
                    self._emit(result)

            now = time.monotonic()
            if now - last_evict >= self._EVICT_INTERVAL:
                self._reassembler.evict_stale(time.time())
                last_evict = now

    def _emit(self, result: Dict[str, Any]):
        meta = result.get('meta') or {}
        payload_type = meta.get('payload_type')
        try:
            payload = udp_protocol.decode_payload(payload_type, result['payload_bytes'], meta)
        except udp_protocol.DecodeError as e:
            self.error_count += 1
            self.report_error(f"UDP In: failed to decode payload ({payload_type}): {e}")
            return

        topic = meta.get('topic', '') or ''
        extra = meta.get('extra') or {}
        if not isinstance(extra, dict):
            extra = {}
        # payload/topic travel in dedicated fields; a (misbehaving) sender
        # including them in extra would raise a duplicate-kwarg TypeError below.
        extra.pop('payload', None)
        extra.pop('topic', None)

        # Underscore props (_msgid, _timestamp_orig, ...) in extra override the
        # fresh ones create_message generates - that is what replicates the
        # sender's message exactly when the sender forwards its props.
        msg = self.create_message(payload=payload, topic=topic, **extra)
        self.received_count += 1
        self.send(msg)
