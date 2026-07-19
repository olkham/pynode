#!/usr/bin/env python3
"""Standalone PNB1 bridge diagnostic - no PyNode install needed (stdlib only).

Copy this single file to any machine (e.g. the Node-RED host) and use it to
answer the two questions that matter when the bridge "doesn't work":

1. **Are datagrams actually arriving at this machine?** Run the listener on
   the port your Node-RED ``udp in`` node uses (stop/redeploy Node-RED first
   so the port is free, or pick a spare port and point PyNode at it)::

       python3 udp_probe.py listen 7401

   Every PNB1 datagram is printed with its header fields; complete messages
   are decoded and summarised. If PyNode is sending and NOTHING prints here,
   the problem is network-level (wrong Host on the PyNode "Node-RED Out"
   node, firewall, fragment-dropping router), not Node-RED.

2. **Does the Node-RED flow itself work?** Run the sender ON the Node-RED
   host so no network is involved, pointing at the ``udp in`` port::

       python3 udp_probe.py send 127.0.0.1 7401 "hello from probe"

   If the flow's debug node prints the message, the flow is fine and the
   problem is upstream (see question 1).

The header layout here is a hand-inlined copy of
``pynode/nodes/NodeRedNode/bridge_protocol.py`` (16 bytes, ``>4sBBIHHH``).
"""

import json
import socket
import struct
import sys
import time

MAGIC = b'PNB1'
HEADER_FORMAT = '>4sBBIHHH'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 16


def listen(port: int, bind_host: str = '0.0.0.0'):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    except OSError:
        pass
    sock.bind((bind_host, port))
    print(f'listening on {bind_host}:{port} (ctrl-c to stop)', flush=True)
    partial = {}  # (addr, message_id) -> {index: body}, meta from chunk 0
    while True:
        data, addr = sock.recvfrom(65535)
        now = time.strftime('%H:%M:%S')
        if len(data) < HEADER_SIZE or data[:4] != MAGIC:
            print(f'{now} {addr[0]}:{addr[1]} NON-PNB1 datagram, {len(data)} bytes,'
                  f' first bytes {data[:8]!r}', flush=True)
            continue
        magic, ver, flags, msg_id, idx, count, meta_len = struct.unpack(
            HEADER_FORMAT, data[:HEADER_SIZE])
        body = data[HEADER_SIZE:]
        print(f'{now} {addr[0]}:{addr[1]} PNB1 v{ver} flags={flags:#04x} '
              f'msg={msg_id} chunk {idx + 1}/{count} body={len(body)}B', flush=True)
        key = (addr[0], msg_id)
        entry = partial.setdefault(key, {})
        entry[idx] = body
        if len(entry) == count:
            del partial[key]
            chunks = b''.join(entry[i] for i in range(count))
            meta_raw, payload = chunks[:meta_len], chunks[meta_len:]
            try:
                meta = json.loads(meta_raw.decode('utf-8'))
            except (ValueError, UnicodeDecodeError) as exc:
                print(f'    COMPLETE msg={msg_id} but metadata unparseable: {exc}',
                      flush=True)
                continue
            ptype = meta.get('payload_type')
            preview = (payload[:80].decode("utf-8", "replace")
                       if ptype == 'json' else f'{payload[:16].hex()}...')
            print(f'    COMPLETE msg={msg_id} type={ptype} '
                  f'topic={meta.get("topic", "")!r} '
                  f'payload={len(payload)}B (total_size={meta.get("total_size")}) '
                  f'preview: {preview}', flush=True)


def send(host: str, port: int, text: str):
    payload = json.dumps(text).encode('utf-8')
    meta = json.dumps({'payload_type': 'json', 'total_size': len(payload),
                       'topic': 'probe'}).encode('utf-8')
    header = struct.pack(HEADER_FORMAT, MAGIC, 1, 0, int(time.time()) & 0xFFFFFFFF,
                         0, 1, len(meta))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(header + meta + payload, (host, port))
    sock.close()
    print(f'sent 1 PNB1 json datagram ({len(header) + len(meta) + len(payload)}B) '
          f'to {host}:{port}')


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'listen':
        listen(int(sys.argv[2]))
    elif len(sys.argv) >= 4 and sys.argv[1] == 'send':
        send(sys.argv[2], int(sys.argv[3]),
             sys.argv[4] if len(sys.argv) > 4 else 'hello from udp_probe')
    else:
        print(__doc__)
        sys.exit(1)
