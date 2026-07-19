"""Node-RED TCP In - receives newline-delimited JSON messages over TCP.

The TCP counterpart to ``NodeRedInNode`` (UDP/PNB1). Listens as a TCP
server; each connected client (a Node-RED ``tcp out`` node in "Connect to"
mode, another PyNode's 'Node-RED TCP Out' node, or anything that writes one
JSON object per line) produces one emitted message per line.

Sending from Node-RED needs one tiny function node before ``tcp out``::

    msg.payload = JSON.stringify({payload: msg.payload, topic: msg.topic || ''}) + "\\n";
    return msg;

A line that is a bare JSON value (not an object with a "payload" key) is
treated as the payload itself, so even that function is optional for plain
JSON payloads followed by a newline.
"""

import socket
import threading
from typing import Optional

from pynode.nodes.base_node import BaseNode, Info
from pynode.nodes.NodeRedNode import ndjson_protocol

_info = Info()
_info.add_text(
    "Listens for TCP connections and emits one message per received JSON "
    "line (NDJSON). Pair with Node-RED's core 'tcp out' node in 'Connect "
    "to' mode (see the node's module docs / bundled README for the one-line "
    "function that formats the line), or with a PyNode 'Node-RED TCP Out' "
    "node.")
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "One message per line: an object line with a 'payload' key "
                  "becomes the full message (topic + extra props restored, "
                  "base64 _pnb marker payloads decoded back to numpy/bytes); "
                  "any other JSON value becomes msg.payload directly."),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Bind Host:", "0.0.0.0 to accept from anywhere, 127.0.0.1 for "
                   "same-machine only."),
    ("Port:", "TCP port to listen on."),
)
_info.add_header("Notes")
_info.add_bullets(
    ("Multiple senders:", "up to 16 concurrent connections are accepted; "
                          "lines from all of them are emitted in arrival "
                          "order."),
    ("No encryption or authentication:", "anyone who can reach the port can "
                                         "inject messages - do not expose it "
                                         "to an untrusted network."),
)


class NodeRedTcpInNode(BaseNode):
    """TCP server emitting one message per received NDJSON line."""

    info = str(_info)
    display_name = 'Node-RED TCP In'
    icon = '📥'
    category = 'network'
    color = '#C7A96E'
    border_color = '#8F7A4F'
    text_color = '#000000'
    input_count = 0
    output_count = 1

    DEFAULT_CONFIG = {
        'bind_host': '0.0.0.0',
        'port': 7404,
    }

    properties = [
        {
            'name': 'bind_host',
            'label': 'Bind Host',
            'type': 'text',
            'default': DEFAULT_CONFIG['bind_host'],
            'help': '0.0.0.0 = all interfaces, 127.0.0.1 = local only'
        },
        {
            'name': 'port',
            'label': 'Port',
            'type': 'number',
            'default': DEFAULT_CONFIG['port'],
            'help': 'TCP port to listen on'
        },
    ]

    _ACCEPT_POLL_TIMEOUT = 0.5
    _RECV_BUFFER_SIZE = 65536
    _MAX_CONNECTIONS = 16
    # A line larger than this aborts its connection (guards a stuck or
    # malicious sender that never sends a newline from growing the buffer
    # forever). 64MB comfortably fits a base64'd raw 4K BGR frame.
    _MAX_LINE_BYTES = 64 * 1024 * 1024

    def __init__(self, node_id=None, name="node-red tcp in"):
        super().__init__(node_id, name)
        self._server_socket = None
        self._accept_thread = None
        self._stop_flag = threading.Event()
        self._clients_lock = threading.Lock()
        self._clients = {}  # socket -> reader thread
        self.bound_port: Optional[int] = None
        self.received_count = 0
        self.error_count = 0

    # -- lifecycle ---------------------------------------------------------- #
    def on_start(self):
        super().on_start()

        bind_host = str(self.config.get('bind_host', self.DEFAULT_CONFIG['bind_host']))
        port = self.get_config_int('port', self.DEFAULT_CONFIG['port'])

        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((bind_host, port))
            server.listen(self._MAX_CONNECTIONS)
            server.settimeout(self._ACCEPT_POLL_TIMEOUT)
        except OSError as e:
            self.report_error(
                f"Node-RED TCP In: failed to listen on {bind_host}:{port}: {e}")
            return

        self._server_socket = server
        self.bound_port = server.getsockname()[1]
        self.received_count = 0

        self._stop_flag.clear()
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def on_stop(self):
        self._stop_flag.set()

        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None

        # Closing client sockets unblocks their reader threads' recv().
        with self._clients_lock:
            clients = dict(self._clients)
        for sock in clients:
            try:
                sock.close()
            except OSError:
                pass
        if self._accept_thread and self._accept_thread.is_alive():
            self._accept_thread.join(timeout=2.0)
        self._accept_thread = None
        for thread in clients.values():
            if thread.is_alive():
                thread.join(timeout=2.0)
        with self._clients_lock:
            self._clients.clear()

        super().on_stop()

    # -- server internals --------------------------------------------------- #
    def _accept_loop(self):
        while not self._stop_flag.is_set():
            try:
                client, addr = self._server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return  # socket closed by on_stop

            with self._clients_lock:
                if len(self._clients) >= self._MAX_CONNECTIONS:
                    try:
                        client.close()
                    except OSError:
                        pass
                    continue
                thread = threading.Thread(
                    target=self._reader_loop, args=(client, addr), daemon=True)
                self._clients[client] = thread
            thread.start()

    def _reader_loop(self, client: socket.socket, addr):
        """Read one connection, emitting a message per complete line."""
        buffer = bytearray()
        reported_bad_line = False
        try:
            client.settimeout(self._ACCEPT_POLL_TIMEOUT)
            while not self._stop_flag.is_set():
                try:
                    data = client.recv(self._RECV_BUFFER_SIZE)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break  # peer closed
                buffer.extend(data)
                if len(buffer) > self._MAX_LINE_BYTES:
                    self.report_error(
                        f"Node-RED TCP In: line from {addr[0]} exceeded "
                        f"{self._MAX_LINE_BYTES} bytes without a newline; "
                        f"closing connection")
                    break
                while True:
                    newline = buffer.find(b'\n')
                    if newline < 0:
                        break
                    line = bytes(buffer[:newline])
                    del buffer[:newline + 1]
                    if line.strip():
                        reported_bad_line = self._handle_line(
                            line, addr, reported_bad_line)
        finally:
            try:
                client.close()
            except OSError:
                pass
            with self._clients_lock:
                self._clients.pop(client, None)

    def _handle_line(self, line: bytes, addr, already_reported: bool) -> bool:
        """Decode + emit one line. Returns the updated bad-line-reported flag."""
        try:
            payload, topic, extra = ndjson_protocol.parse_line(line)
        except ndjson_protocol.NdjsonError as e:
            self.error_count += 1
            if not already_reported:
                # One report per connection, not per bad line - a misconfigured
                # sender (e.g. non-JSON traffic) would flood the error panel.
                self.report_error(
                    f"Node-RED TCP In: undecodable line from {addr[0]} ({e}); "
                    f"further bad lines on this connection are counted "
                    f"silently")
            return True

        extra.pop('payload', None)
        extra.pop('topic', None)
        # Underscore props (_msgid, _timestamp_orig, ...) in extra override
        # the fresh ones create_message generates - exact replication when
        # the sender forwards its props.
        msg = self.create_message(payload=payload, topic=topic, **extra)
        self.received_count += 1
        self.send(msg)
        return already_reported
