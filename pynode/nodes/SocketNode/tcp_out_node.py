"""TCP Out - sends messages over TCP as newline-delimited JSON.

The TCP counterpart to ``UdpOutNode`` (UDP/PNB1). One persistent client
connection to a listening TCP receiver; one JSON line per message. TCP
provides ordering/reliability/unlimited size, so any consumer can read it
with a plain socket read split on newlines followed by JSON.parse - no
custom framing needed. (For example, a Node-RED ``tcp in`` node in "stream
of strings, delimited by \\n" mode feeding a ``json`` node yields the
message object directly.)

Trade-off vs UDP: binary payloads travel base64-wrapped (~33% bigger) and a
slow consumer applies backpressure (the stream stalls rather than dropping
frames) - prefer this for control/telemetry/detections, prefer UDP for
sustained high-rate video.
"""

import socket
import threading
from typing import Any, Dict

from pynode.nodes.base_node import BaseNode, Info
from pynode.nodes.SocketNode import ndjson_protocol

_info = Info()
_info.add_text(
    "Sends each incoming message over a persistent TCP connection as one "
    "JSON line (NDJSON). Any consumer reads it as a stream of newline-"
    "delimited JSON objects - no custom decoding needed. Pair with a PyNode "
    "'TCP In' node, or any TCP listener (e.g. a Node-RED 'tcp in' node in "
    "'stream of strings delimited by \\n' mode feeding a 'json' node).")
_info.add_header("Configuration")
_info.add_bullets(
    ("Host / Port:", "The machine and port where the TCP receiver (a PyNode "
                     "'TCP In' node, or any listening TCP server) is "
                     "listening."),
    ("Encode Images:", "JPEG-encode numpy image payloads (sent as "
                       '{"_pnb": "jpeg", "data": "<base64>"}). When off, '
                       "arrays are sent as base64 raw bytes with dtype/shape "
                       "- only decodable by a PyNode receiver."),
    ("Include Extra Message Properties:", "Forward EVERY msg property other "
                       "than payload/topic (underscore ones included) so the "
                       "receiver replicates the message exactly. Values that "
                       "are not JSON-serializable are skipped individually."),
    ("Reconnect Delay:", "Seconds between reconnection attempts while the "
                         "peer is unreachable. Messages arriving while "
                         "disconnected are dropped (and counted)."),
)
_info.add_header("Notes")
_info.add_bullets(
    ("Reliable but blocking:", "TCP retransmits and preserves order, but a "
                               "slow/stalled consumer backpressures the "
                               "sender (sends time out and drop). For "
                               "sustained high-rate video frames prefer the "
                               "UDP Out node."),
    ("No encryption or authentication:", "do not expose the port to an "
                                         "untrusted network."),
)


class TcpOutNode(BaseNode):
    """Sends messages as NDJSON lines over a persistent TCP connection."""

    info = str(_info)
    display_name = 'TCP Out'
    icon = '📤'
    category = 'network'
    color = '#C7A96E'
    border_color = '#8F7A4F'
    text_color = '#000000'
    input_count = 1
    output_count = 0

    DEFAULT_CONFIG = {
        'host': '127.0.0.1',
        'port': 7403,
        'encode_images': True,
        'jpeg_quality': 80,
        'include_msg_props': False,
        'reconnect_delay': 2.0,
    }

    properties = [
        {
            'name': 'host',
            'label': 'Host',
            'type': 'text',
            'default': DEFAULT_CONFIG['host'],
            'help': "Destination host running the listening TCP receiver (a PyNode TCP In node, or any TCP server)"
        },
        {
            'name': 'port',
            'label': 'Port',
            'type': 'number',
            'default': DEFAULT_CONFIG['port'],
            'help': 'Destination TCP port'
        },
        {
            'name': 'encode_images',
            'label': 'Encode Images as JPEG',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['encode_images'],
            'help': 'JPEG-encode numpy image payloads (base64 in the JSON line)'
        },
        {
            'name': 'jpeg_quality',
            'label': 'JPEG Quality (1-100)',
            'type': 'number',
            'default': DEFAULT_CONFIG['jpeg_quality'],
        },
        {
            'name': 'include_msg_props',
            'label': 'Include Extra Message Properties',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['include_msg_props'],
            'help': 'Forward every msg property besides payload/topic (incl. _msgid, timestamps, ...) so the receiver replicates the message exactly'
        },
        {
            'name': 'reconnect_delay',
            'label': 'Reconnect Delay (s)',
            'type': 'number',
            'default': DEFAULT_CONFIG['reconnect_delay'],
            'help': 'Seconds between reconnect attempts while the peer is unreachable'
        },
    ]

    _CONNECT_TIMEOUT = 3.0
    _SEND_TIMEOUT = 5.0
    # Reconnector poll granularity (bounds shutdown latency independent of
    # the configured reconnect delay).
    _POLL_INTERVAL = 0.25

    def __init__(self, node_id=None, name="tcp out"):
        super().__init__(node_id, name)
        self._socket = None
        self._socket_lock = threading.Lock()
        self._connector_thread = None
        self._stop_flag = threading.Event()
        self._was_connected = False  # for one report per outage, not per msg
        self.sent_count = 0
        self.dropped_count = 0
        self.error_count = 0

    # -- connection management ---------------------------------------------- #
    @property
    def connected(self) -> bool:
        with self._socket_lock:
            return self._socket is not None

    def _connect_once(self, host: str, port: int) -> bool:
        try:
            sock = socket.create_connection((host, port),
                                            timeout=self._CONNECT_TIMEOUT)
            sock.settimeout(self._SEND_TIMEOUT)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
        except OSError:
            return False
        with self._socket_lock:
            if self._stop_flag.is_set():
                sock.close()
                return False
            self._socket = sock
        self._was_connected = True
        return True

    def _drop_connection(self):
        with self._socket_lock:
            sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _connector_loop(self):
        """Keep the connection up: (re)connect whenever it is down."""
        host = str(self.config.get('host', self.DEFAULT_CONFIG['host']))
        port = self.get_config_int('port', self.DEFAULT_CONFIG['port'])
        delay = max(self.get_config_float(
            'reconnect_delay', self.DEFAULT_CONFIG['reconnect_delay']), 0.1)

        while not self._stop_flag.is_set():
            if not self.connected:
                if self._connect_once(host, port):
                    continue
                # Unreachable - wait the configured delay (poll the stop flag)
                if self._was_connected:
                    self._was_connected = False
                    self.report_error(
                        f"TCP Out: connection to {host}:{port} lost, "
                        f"retrying every {delay:g}s")
                if self._stop_flag.wait(delay):
                    return
            else:
                if self._stop_flag.wait(self._POLL_INTERVAL):
                    return

    # -- lifecycle ---------------------------------------------------------- #
    def on_start(self):
        super().on_start()
        self._stop_flag.clear()
        self.sent_count = 0
        self.dropped_count = 0
        self._was_connected = True  # so the first failed connect reports once
        self._connector_thread = threading.Thread(
            target=self._connector_loop, daemon=True)
        self._connector_thread.start()

    def on_stop(self):
        self._stop_flag.set()
        self._drop_connection()
        if self._connector_thread and self._connector_thread.is_alive():
            self._connector_thread.join(timeout=2.0)
        self._connector_thread = None
        super().on_stop()

    # -- sending ------------------------------------------------------------ #
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        try:
            line = ndjson_protocol.build_line(
                msg,
                include_props=self.get_config_bool('include_msg_props', False),
                encode_images=self.get_config_bool('encode_images', True),
                jpeg_quality=self.get_config_int(
                    'jpeg_quality', self.DEFAULT_CONFIG['jpeg_quality']),
            )
        except ndjson_protocol.NdjsonError as e:
            self.error_count += 1
            self.report_error(f"TCP Out: failed to encode message: {e}")
            return

        with self._socket_lock:
            sock = self._socket
        if sock is None:
            # Disconnected - drop silently (the connector already reported the
            # outage once) and count it.
            self.dropped_count += 1
            return

        try:
            sock.sendall(line)
        except OSError as e:
            self.error_count += 1
            self.dropped_count += 1
            self._drop_connection()  # connector will reconnect + report
            self.report_error(f"TCP Out: send failed ({e}); reconnecting")
            return
        self.sent_count += 1
