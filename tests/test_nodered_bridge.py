"""Tests for the PyNode <-> Node-RED UDP bridge (NodeRedOutNode / NodeRedInNode
/ bridge_protocol.py) and the bundled Node-RED-side flow JSON.

Safety
------
* No Flask app, WorkflowManager, or ``workflows/`` directory is touched -
  ``NodeRedOutNode``/``NodeRedInNode`` are instantiated and driven directly,
  exactly as ``tests/conftest.py``'s ``node_classes``-based tests do for other
  node families (see also ``tests/test_zenoh_nodes.py`` for the template this
  file follows).
* Every socket this file opens (the nodes' own UDP sockets, plus the raw
  sender sockets used to feed hand-built datagrams) is bound to
  ``127.0.0.1``/ephemeral port (``0``) only - never port 5000, never a
  wildcard bind for a *sending* socket, never a real interface.
* Every node started with ``on_start()`` is stopped with ``on_stop()`` in a
  ``try/finally`` before the test returns, so its receiver thread and socket
  never outlive the test.
"""

import json
import os
import random
import re
import socket
import time
from pathlib import Path

import numpy as np
import pytest

from pynode.nodes.NodeRedNode import bridge_protocol as bp
from pynode.nodes.NodeRedNode.nodered_in_node import NodeRedInNode
from pynode.nodes.NodeRedNode.nodered_out_node import NodeRedOutNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_until(predicate, timeout=5.0, interval=0.02):
    """Poll ``predicate`` until it's truthy or ``timeout`` elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _make_test_frame():
    """A deterministic 640x480 BGR gradient - not flat (so JPEG loss is
    meaningful to assert on) but smooth (so JPEG loss stays small)."""
    y, x = np.mgrid[0:480, 0:640]
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :, 0] = (x % 256).astype(np.uint8)
    frame[:, :, 1] = (y % 256).astype(np.uint8)
    frame[:, :, 2] = ((x + y) % 256).astype(np.uint8)
    return frame


def _make_in_node(sink, reassembly_timeout=2.0):
    """A started NodeRedInNode bound to an ephemeral loopback port, wired to
    ``sink``. Caller must call ``.on_stop()`` (in a finally block)."""
    node = NodeRedInNode(name='node-red-in')
    node.configure({
        'bind_host': '127.0.0.1',
        'port': 0,
        'reassembly_timeout': reassembly_timeout,
    })
    node.connect(sink)
    node.on_start()
    assert node.bound_port, "NodeRedInNode failed to bind (bound_port is falsy)"
    return node


def _make_out_node(target_port, chunk_size=None, encode_images=True, include_msg_props=False):
    """A started NodeRedOutNode targeting 127.0.0.1:target_port."""
    node = NodeRedOutNode(name='node-red-out')
    cfg = {
        'host': '127.0.0.1',
        'port': target_port,
        'encode_images': encode_images,
        'include_msg_props': include_msg_props,
    }
    if chunk_size is not None:
        cfg['chunk_size'] = str(chunk_size)
    node.configure(cfg)
    node.on_start()
    return node


# ===========================================================================
# Pure protocol unit tests (bridge_protocol.py only - no sockets)
# ===========================================================================

def test_header_size_and_format():
    assert bp.HEADER_SIZE == 16
    assert bp.HEADER_FORMAT == '>4sBBIHHH'


def test_header_pack_unpack_exact_layout():
    """Pack a header, verify its raw bytes with struct directly (not through
    the module's own unpack), then verify unpack_header agrees."""
    header = bp.pack_header(flags=0x03, message_id=123456, chunk_index=2,
                            chunk_count=5, meta_length=17, version=1)
    assert len(header) == 16

    import struct
    magic, version, flags, message_id, chunk_index, chunk_count, meta_length = \
        struct.unpack('>4sBBIHHH', header)
    assert magic == b'PNB1'
    assert version == 1
    assert flags == 0x03
    assert message_id == 123456
    assert chunk_index == 2
    assert chunk_count == 5
    assert meta_length == 17

    parsed = bp.unpack_header(header)
    assert (parsed.version, parsed.flags, parsed.message_id, parsed.chunk_index,
            parsed.chunk_count, parsed.meta_length) == (1, 0x03, 123456, 2, 5, 17)
    assert parsed.is_binary is True
    assert parsed.is_jpeg is True


def test_unpack_header_rejects_bad_magic():
    bad = b'XXXX' + b'\x00' * 12
    with pytest.raises(bp.DecodeError):
        bp.unpack_header(bad)


def test_unpack_header_rejects_short_datagram():
    with pytest.raises(bp.DecodeError):
        bp.unpack_header(b'PNB1\x01\x00')


def test_unpack_header_rejects_invalid_chunk_index():
    header = bp.pack_header(flags=0, message_id=1, chunk_index=5, chunk_count=3, meta_length=0)
    with pytest.raises(bp.DecodeError):
        bp.unpack_header(header)


def _reassemble_all(datagrams, addr=('127.0.0.1', 1)):
    """Feed every datagram through a fresh Reassembler; return the completed
    message dict (asserts exactly one completion) and the reassembler."""
    reassembler = bp.Reassembler()
    result = None
    for d in datagrams:
        r = reassembler.add_datagram(addr, d)
        if r is not None:
            assert result is None, "reassembler completed twice"
            result = r
    assert result is not None, "reassembler never completed"
    return result, reassembler


@pytest.mark.parametrize('payload', [
    {'a': 1, 'b': [1, 2, 3], 'c': 'hello', 'd': None, 'e': True},
    [1, 2, 3, 'x'],
    'plain string payload',
    42,
    3.14,
    None,
])
def test_roundtrip_json_single_chunk(payload):
    datagrams = bp.build_datagrams(42, 'my/topic', payload)
    assert len(datagrams) == 1
    header = bp.unpack_header(datagrams[0])
    assert (header.message_id, header.chunk_index, header.chunk_count, header.flags) == (42, 0, 1, 0)

    result, reassembler = _reassemble_all(datagrams)
    assert result['meta']['payload_type'] == bp.PayloadType.JSON
    assert result['meta']['topic'] == 'my/topic'
    decoded = bp.decode_payload(result['meta']['payload_type'], result['payload_bytes'], result['meta'])
    assert decoded == payload
    assert reassembler.pending == {}


def test_roundtrip_json_multi_chunk():
    payload = {'items': list(range(2000)), 'note': 'a fairly large JSON body'}
    datagrams = bp.build_datagrams(6, '', payload, chunk_size=200)
    assert len(datagrams) > 1
    result, reassembler = _reassemble_all(datagrams)
    decoded = bp.decode_payload(result['meta']['payload_type'], result['payload_bytes'], result['meta'])
    assert decoded == payload
    assert reassembler.pending == {}


def test_roundtrip_bytes_single_chunk():
    payload = b'\x00\x01\x02hello\xff\xfe'
    datagrams = bp.build_datagrams(5, 't', payload)
    assert len(datagrams) == 1
    header = bp.unpack_header(datagrams[0])
    assert header.flags == bp.FLAG_BINARY
    result, _ = _reassemble_all(datagrams)
    decoded = bp.decode_payload(result['meta']['payload_type'], result['payload_bytes'], result['meta'])
    assert decoded == payload
    assert isinstance(decoded, bytes)


def test_roundtrip_bytes_multi_chunk():
    payload = bytes(range(256)) * 500  # 128000 bytes
    datagrams = bp.build_datagrams(1, '', payload, chunk_size=1000)
    assert len(datagrams) > 1
    for d in datagrams:
        header = bp.unpack_header(d)
        assert header.flags == bp.FLAG_BINARY
        assert header.chunk_count == len(datagrams)
    result, reassembler = _reassemble_all(datagrams)
    decoded = bp.decode_payload(result['meta']['payload_type'], result['payload_bytes'], result['meta'])
    assert decoded == payload
    assert reassembler.pending == {}


def test_roundtrip_jpeg_multi_chunk():
    frame = _make_test_frame()
    datagrams = bp.build_datagrams(2, 'cam', frame, encode_images=True, chunk_size=2000)
    assert len(datagrams) > 1
    header = bp.unpack_header(datagrams[0])
    assert header.flags == (bp.FLAG_BINARY | bp.FLAG_JPEG)

    result, reassembler = _reassemble_all(datagrams)
    assert result['meta']['payload_type'] == bp.PayloadType.JPEG
    decoded = bp.decode_payload(result['meta']['payload_type'], result['payload_bytes'], result['meta'])
    assert isinstance(decoded, np.ndarray)
    assert decoded.shape == frame.shape
    diff = float(np.mean(np.abs(decoded.astype(np.int16) - frame.astype(np.int16))))
    assert diff < 5.0, f"JPEG round-trip mean abs diff too high: {diff}"
    assert reassembler.pending == {}


def test_roundtrip_raw_numpy():
    arr = (np.random.RandomState(3).rand(10, 20, 3) * 1000).astype(np.float32)
    datagrams = bp.build_datagrams(3, '', arr, encode_images=False, chunk_size=97)
    assert len(datagrams) > 1
    header = bp.unpack_header(datagrams[0])
    assert header.flags == bp.FLAG_BINARY  # binary but not jpeg

    result, reassembler = _reassemble_all(datagrams)
    assert result['meta']['payload_type'] == bp.PayloadType.RAW_NUMPY
    assert result['meta']['dtype'] == 'float32'
    assert result['meta']['shape'] == [10, 20, 3]
    decoded = bp.decode_payload(result['meta']['payload_type'], result['payload_bytes'], result['meta'])
    np.testing.assert_array_equal(decoded, arr)
    assert decoded.dtype == arr.dtype
    assert reassembler.pending == {}


def test_raw_numpy_decode_returns_fresh_writable_buffer():
    """decode_payload for raw_numpy must not return a read-only view onto the
    input bytes (np.frombuffer alone would) - a fresh buffer per message."""
    arr = np.arange(24, dtype=np.int32).reshape(2, 3, 4)
    payload_bytes = arr.tobytes()
    meta = {'dtype': 'int32', 'shape': [2, 3, 4]}
    decoded = bp.decode_payload(bp.PayloadType.RAW_NUMPY, payload_bytes, meta)
    assert decoded.flags.writeable
    decoded[0, 0, 0] = 999  # would raise ValueError on a read-only frombuffer view
    assert decoded[0, 0, 0] == 999
    np.testing.assert_array_equal(np.frombuffer(payload_bytes, dtype=np.int32).reshape(2, 3, 4), arr)


def test_encode_unsupported_payload_raises():
    class Unsupported:
        pass
    with pytest.raises(bp.EncodeError):
        bp.build_datagrams(1, '', Unsupported())


def test_message_id_wraparound_pure():
    assert bp.next_message_id(bp.MAX_MESSAGE_ID) == 0
    assert bp.next_message_id(0) == 1
    assert bp.next_message_id(bp.MAX_MESSAGE_ID - 1) == bp.MAX_MESSAGE_ID

    datagrams_max = bp.build_datagrams(bp.MAX_MESSAGE_ID, '', {'x': 1})
    assert bp.unpack_header(datagrams_max[0]).message_id == bp.MAX_MESSAGE_ID

    datagrams_wrapped = bp.build_datagrams(bp.next_message_id(bp.MAX_MESSAGE_ID), '', {'x': 2})
    assert bp.unpack_header(datagrams_wrapped[0]).message_id == 0


def test_extra_props_roundtrip_pure():
    datagrams = bp.build_datagrams(9, 'topic/a', {'v': 1}, extra_props={'frame_count': 7, 'source': 'unit-test'})
    result, _ = _reassemble_all(datagrams)
    assert result['meta']['extra'] == {'frame_count': 7, 'source': 'unit-test'}


def test_reassembler_evicts_incomplete_after_timeout_pure():
    """Deterministic (no thread/sleep dependency on a poll loop): manually
    drive evict_stale() with an explicit 'now' after the configured timeout."""
    reassembler = bp.Reassembler(timeout=1.0)
    datagrams = bp.build_datagrams(9, '', b'x' * 5000, chunk_size=100)
    assert len(datagrams) > 1

    start = 1000.0
    for d in datagrams[:-1]:  # withhold the last chunk -> never completes
        result = reassembler.add_datagram(('z', 1), d, now=start)
        assert result is None
    assert reassembler.pending_count == 1
    assert reassembler.stats['dropped_timeout'] == 0

    evicted = reassembler.evict_stale(now=start + 1.5)
    assert evicted == 1
    assert reassembler.pending == {}
    assert reassembler.stats['dropped_timeout'] == 1


def test_reassembler_no_premature_eviction_pure():
    reassembler = bp.Reassembler(timeout=5.0)
    datagrams = bp.build_datagrams(1, '', b'x' * 5000, chunk_size=100)
    start = 1000.0
    for d in datagrams[:-1]:
        reassembler.add_datagram(('z', 1), d, now=start)
    evicted = reassembler.evict_stale(now=start + 1.0)  # well under the 5s timeout
    assert evicted == 0
    assert reassembler.pending_count == 1


def test_reassembler_overflow_evicts_oldest_pure():
    reassembler = bp.Reassembler(timeout=1000.0, max_incomplete=3)
    for mid in range(4):
        datagrams = bp.build_datagrams(mid, '', b'x' * 5000, chunk_size=100)
        # only send chunk 0 -> stays incomplete
        reassembler.add_datagram((f'addr{mid}', 1), datagrams[0], now=1000.0 + mid)
    assert reassembler.pending_count == 3
    assert reassembler.stats['dropped_overflow'] == 1


def test_reassembler_stats_counters_pure():
    reassembler = bp.Reassembler()
    # chunk_size must exceed the metadata's own JSON size (~35-45 bytes) for
    # any payload bytes to fit in chunk 0; use a payload big enough that a
    # small chunk_size still yields several chunks.
    datagrams = bp.build_datagrams(1, '', {'a': list(range(50))}, chunk_size=60)
    assert len(datagrams) > 1
    for d in datagrams:
        reassembler.add_datagram(('s', 1), d)
    assert reassembler.stats['received_datagrams'] == len(datagrams)
    assert reassembler.stats['completed'] == 1

    # A duplicate delivery of the final chunk bumps duplicate_chunks and does
    # not re-complete (message already removed from pending).
    dup = reassembler.add_datagram(('s', 1), datagrams[-1])
    assert dup is None

    # Bad-magic datagram bumps decode_errors, no crash.
    reassembler.add_datagram(('s', 1), b'NOPE' + b'\x00' * 12)
    assert reassembler.stats['decode_errors'] == 1


def test_reassembler_out_of_order_pure():
    datagrams = bp.build_datagrams(11, 'shuffled', {'k': list(range(300))}, chunk_size=64)
    assert len(datagrams) >= 4
    shuffled = datagrams[:]
    random.Random(1234).shuffle(shuffled)
    result, reassembler = _reassemble_all(shuffled)
    decoded = bp.decode_payload(result['meta']['payload_type'], result['payload_bytes'], result['meta'])
    assert decoded == {'k': list(range(300))}
    assert reassembler.pending == {}


# ===========================================================================
# Real loopback tests: NodeRedOutNode -> UDP -> NodeRedInNode
# ===========================================================================

def test_roundtrip_small_json_real_node(node_classes):
    sink = node_classes['sink'](name='sink')
    in_node = _make_in_node(sink)
    out_node = _make_out_node(in_node.bound_port)
    try:
        msg = out_node.create_message(payload={'hello': 'world'}, topic='demo/topic')
        out_node.on_input(msg)

        assert _wait_until(lambda: len(sink.received) == 1)
        received = sink.received[0]
        assert received['payload'] == {'hello': 'world'}
        assert received['topic'] == 'demo/topic'
        assert out_node.sent_count == 1
        assert in_node.received_count == 1
    finally:
        out_node.on_stop()
        in_node.on_stop()


def test_roundtrip_1mb_binary_multichunk_real_node(node_classes):
    sink = node_classes['sink'](name='sink')
    in_node = _make_in_node(sink)
    out_node = _make_out_node(in_node.bound_port)
    try:
        payload = os.urandom(1024 * 1024)
        out_node.on_input(out_node.create_message(payload=payload))

        assert _wait_until(lambda: len(sink.received) == 1, timeout=15.0)
        assert sink.received[0]['payload'] == payload
    finally:
        out_node.on_stop()
        in_node.on_stop()


def test_roundtrip_numpy_frame_encode_images_on_real_node(node_classes):
    sink = node_classes['sink'](name='sink')
    in_node = _make_in_node(sink)
    out_node = _make_out_node(in_node.bound_port, encode_images=True)
    try:
        frame = _make_test_frame()
        out_node.on_input(out_node.create_message(payload=frame, topic='cam'))

        assert _wait_until(lambda: len(sink.received) == 1, timeout=10.0)
        decoded = sink.received[0]['payload']
        assert isinstance(decoded, np.ndarray)
        assert decoded.shape == frame.shape
        diff = float(np.mean(np.abs(decoded.astype(np.int16) - frame.astype(np.int16))))
        assert diff < 5.0, f"JPEG round-trip mean abs diff too high: {diff}"
    finally:
        out_node.on_stop()
        in_node.on_stop()


def test_roundtrip_numpy_frame_encode_images_off_real_node(node_classes):
    sink = node_classes['sink'](name='sink')
    in_node = _make_in_node(sink)
    out_node = _make_out_node(in_node.bound_port, encode_images=False)
    try:
        frame = _make_test_frame()
        out_node.on_input(out_node.create_message(payload=frame))

        assert _wait_until(lambda: len(sink.received) == 1, timeout=10.0)
        decoded = sink.received[0]['payload']
        assert isinstance(decoded, np.ndarray)
        np.testing.assert_array_equal(decoded, frame)
        assert decoded.dtype == frame.dtype
    finally:
        out_node.on_stop()
        in_node.on_stop()


def test_include_msg_props_real_node(node_classes):
    sink = node_classes['sink'](name='sink')
    in_node = _make_in_node(sink)
    out_node = _make_out_node(in_node.bound_port, include_msg_props=True)
    try:
        msg = out_node.create_message(payload={'v': 1}, topic='t', frame_count=42, custom='abc')
        out_node.on_input(msg)

        assert _wait_until(lambda: len(sink.received) == 1)
        received = sink.received[0]
        assert received.get('frame_count') == 42
        assert received.get('custom') == 'abc'
    finally:
        out_node.on_stop()
        in_node.on_stop()


def test_message_id_wraparound_real_node(node_classes):
    sink = node_classes['sink'](name='sink')
    in_node = _make_in_node(sink)
    out_node = _make_out_node(in_node.bound_port)
    try:
        out_node._message_id = bp.MAX_MESSAGE_ID - 1  # next two sends: MAX, then 0
        out_node.on_input(out_node.create_message(payload={'n': 1}))
        out_node.on_input(out_node.create_message(payload={'n': 2}))

        assert _wait_until(lambda: len(sink.received) == 2)
        received_ns = sorted(m['payload']['n'] for m in sink.received)
        assert received_ns == [1, 2]
        assert out_node._message_id == 0  # wrapped back to 0
    finally:
        out_node.on_stop()
        in_node.on_stop()


def test_stats_counters_real_node(node_classes):
    sink = node_classes['sink'](name='sink')
    in_node = _make_in_node(sink)
    out_node = _make_out_node(in_node.bound_port)
    try:
        for i in range(5):
            out_node.on_input(out_node.create_message(payload={'i': i}))

        assert _wait_until(lambda: len(sink.received) == 5)
        assert out_node.sent_count == 5
        assert out_node.error_count == 0
        assert in_node.received_count == 5
        assert in_node._reassembler.stats['completed'] == 5
        assert in_node._reassembler.stats['received_datagrams'] == 5  # each msg fits in 1 datagram
        assert in_node._reassembler.pending == {}
    finally:
        out_node.on_stop()
        in_node.on_stop()


def test_out_of_order_chunk_delivery_real_node(node_classes):
    """Hand-build a multi-chunk message and feed it to a real NodeRedInNode
    via a raw socket, in shuffled order - reassembly must not depend on
    arrival order."""
    sink = node_classes['sink'](name='sink')
    in_node = _make_in_node(sink)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.bind(('127.0.0.1', 0))
    try:
        payload = {'items': list(range(500)), 'note': 'shuffle me'}
        # chunk_size must exceed the metadata's JSON size (topic + payload_type
        # + total_size is ~65 bytes here); 128 leaves room while still forcing
        # many chunks for a 500-item payload.
        datagrams = bp.build_datagrams(77, 'shuffle/topic', payload, chunk_size=128)
        assert len(datagrams) >= 4

        shuffled = datagrams[:]
        random.Random(4321).shuffle(shuffled)
        for d in shuffled:
            sender.sendto(d, ('127.0.0.1', in_node.bound_port))

        assert _wait_until(lambda: len(sink.received) == 1)
        received = sink.received[0]
        assert received['payload'] == payload
        assert received['topic'] == 'shuffle/topic'
        assert in_node._reassembler.pending == {}
    finally:
        sender.close()
        in_node.on_stop()


def test_missing_chunk_eviction_real_node(node_classes):
    """A message with a dropped chunk must never be emitted, and the
    reassembler's pending buffer must not leak it after the receiver
    thread's own periodic eviction sweep runs."""
    sink = node_classes['sink'](name='sink')
    in_node = _make_in_node(sink, reassembly_timeout=0.1)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.bind(('127.0.0.1', 0))
    try:
        payload = os.urandom(20000)
        datagrams = bp.build_datagrams(5, '', payload, chunk_size=1000)
        assert len(datagrams) >= 3

        for d in datagrams[:-1]:  # withhold the last chunk
            sender.sendto(d, ('127.0.0.1', in_node.bound_port))

        # Wait past reassembly_timeout + the node's eviction sweep interval.
        time.sleep(0.1 + NodeRedInNode._EVICT_INTERVAL + 0.4)

        assert sink.received == []
        assert in_node._reassembler.pending == {}
        assert in_node._reassembler.stats['dropped_timeout'] >= 1
        assert in_node.received_count == 0
    finally:
        sender.close()
        in_node.on_stop()


class _FailingSocket:
    """Stand-in for a real UDP socket whose sendto() always fails.

    socket.socket's ``sendto`` attribute is a read-only C slot (cannot be
    monkeypatched on a real socket instance), so the node's ``_socket`` is
    swapped for this plain-Python fake instead - no real socket is ever
    opened by this test.
    """

    def sendto(self, *args, **kwargs):
        raise OSError("simulated send failure")

    def close(self):
        pass


def test_out_node_socket_error_reports_once_per_burst(node_classes):
    """A send failure for one message must call report_error once, not once
    per chunk (a multi-chunk message that fails should not spam)."""
    out_node = NodeRedOutNode(name='node-red-out')
    out_node.configure({'host': '127.0.0.1', 'port': 7401, 'chunk_size': '50'})
    errors = []
    out_node._workflow_engine = type('FakeEngine', (), {
        'broadcast_error': staticmethod(lambda node_id, name, msg: errors.append(msg))
    })()
    out_node._socket = _FailingSocket()  # every sendto() call raises
    try:
        big_payload = b'x' * 5000  # guarantees multiple chunks at chunk_size=50
        out_node.on_input(out_node.create_message(payload=big_payload))

        assert len(errors) == 1
        assert out_node.sent_count == 0
        assert out_node.error_count == 1
    finally:
        out_node.on_stop()


# ===========================================================================
# Node-RED-side flow JSON validation
# ===========================================================================

FLOW_JSON_PATH = (Path(__file__).resolve().parent.parent / 'pynode' / 'nodes' /
                  'NodeRedNode' / 'nodered' / 'pynode-bridge-flow.json')


def _load_flow():
    return json.loads(FLOW_JSON_PATH.read_text(encoding='utf-8'))


def test_flow_json_well_formed():
    data = _load_flow()
    assert isinstance(data, list) and data, "flow JSON must be a non-empty list of nodes"

    ids = [n['id'] for n in data]
    assert len(ids) == len(set(ids)), "duplicate node ids in flow JSON"
    id_set = set(ids)

    types = {n['type'] for n in data}
    assert 'tab' in types
    assert 'udp in' in types
    assert 'udp out' in types
    assert 'function' in types

    # Every wire target must reference a node id that actually exists.
    for node in data:
        for port in (node.get('wires') or []):
            for target in port:
                assert target in id_set, f"dangling wire target {target!r} in node {node.get('id')!r}"

    func_names = {n['name'] for n in data if n['type'] == 'function'}
    assert 'PNB1 reassemble' in func_names
    assert 'PNB1 chunk+send' in func_names

    # udp in / out ports are present and numeric-looking (Node-RED stores them as strings).
    udp_in = next(n for n in data if n['type'] == 'udp in')
    udp_out = next(n for n in data if n['type'] == 'udp out')
    assert str(udp_in['port']).isdigit()
    assert str(udp_out['port']).isdigit()
    assert udp_in['datatype'] == 'buffer', "udp in must output raw Buffer for PNB1 header parsing"


def _extract_js_int_const(js_src, name):
    m = re.search(rf'const\s+{re.escape(name)}\s*=\s*(0x[0-9a-fA-F]+|\d+)\s*;', js_src)
    assert m, f"constant {name} not found in JS source"
    text = m.group(1)
    return int(text, 16) if text.lower().startswith('0x') else int(text)


def _extract_js_str_const(js_src, name):
    m = re.search(rf"const\s+{re.escape(name)}\s*=\s*'([^']*)'\s*;", js_src)
    assert m, f"string constant {name} not found in JS source"
    return m.group(1)


def test_flow_json_constants_match_python():
    """The two function nodes' embedded JS constants must byte-for-byte match
    bridge_protocol.py - this is the only automated guard against the JS
    mirror silently drifting from the Python implementation it must match."""
    data = _load_flow()
    func_src = {n['name']: n['func'] for n in data if n['type'] == 'function'}
    assert 'PNB1 reassemble' in func_src and 'PNB1 chunk+send' in func_src

    for name, js in func_src.items():
        assert _extract_js_str_const(js, 'MAGIC') == bp.MAGIC.decode('ascii'), name
        assert _extract_js_int_const(js, 'HEADER_VERSION') == bp.HEADER_VERSION, name
        assert _extract_js_int_const(js, 'HEADER_SIZE') == bp.HEADER_SIZE, name
        assert _extract_js_int_const(js, 'FLAG_BINARY') == bp.FLAG_BINARY, name
        assert _extract_js_int_const(js, 'FLAG_JPEG') == bp.FLAG_JPEG, name

    reassemble_js = func_src['PNB1 reassemble']
    assert _extract_js_int_const(reassemble_js, 'DEFAULT_REASSEMBLY_TIMEOUT_MS') == \
        int(bp.DEFAULT_REASSEMBLY_TIMEOUT * 1000)
    assert _extract_js_int_const(reassemble_js, 'MAX_INCOMPLETE') == bp.DEFAULT_MAX_INCOMPLETE

    chunk_send_js = func_src['PNB1 chunk+send']
    assert _extract_js_int_const(chunk_send_js, 'DEFAULT_CHUNK_SIZE') == bp.DEFAULT_CHUNK_SIZE
    assert _extract_js_int_const(chunk_send_js, 'MTU_CHUNK_SIZE') == bp.MTU_CHUNK_SIZE


def test_flow_json_header_offsets_match_struct_layout():
    """The JS Buffer.read*/write* byte offsets must match HEADER_FORMAT
    '>4sBBIHHH': version=4, flags=5, message_id=6, chunk_index=10,
    chunk_count=12, meta_length=14 (magic occupies bytes 0-3)."""
    expected_offsets = {'4', '5', '6', '10', '12', '14'}
    data = _load_flow()
    func_src = {n['name']: n['func'] for n in data if n['type'] == 'function'}

    read_offsets = set(re.findall(r'read(?:UInt8|UInt16BE|UInt32BE)\((\d+)\)', func_src['PNB1 reassemble']))
    assert expected_offsets <= read_offsets, f"missing header field reads: {expected_offsets - read_offsets}"

    write_offsets = set(re.findall(r'write(?:UInt8|UInt16BE|UInt32BE)\([^,]+,\s*(\d+)\)',
                                   func_src['PNB1 chunk+send']))
    assert expected_offsets <= write_offsets, f"missing header field writes: {expected_offsets - write_offsets}"
