"""Tests for the UDP / TCP socket nodes (UdpOutNode / UdpInNode /
udp_protocol.py, TcpOutNode / TcpInNode / ndjson_protocol.py) and the
bundled example Node-RED interop flow JSON.

Safety
------
* No Flask app, WorkflowManager, or ``workflows/`` directory is touched -
  ``UdpOutNode``/``UdpInNode`` are instantiated and driven directly,
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

from pynode.nodes.SocketNode import udp_protocol as bp
from pynode.nodes.SocketNode.udp_in_node import UdpInNode
from pynode.nodes.SocketNode.udp_out_node import UdpOutNode


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
    """A started UdpInNode bound to an ephemeral loopback port, wired to
    ``sink``. Caller must call ``.on_stop()`` (in a finally block)."""
    node = UdpInNode(name='udp-in')
    node.configure({
        'bind_host': '127.0.0.1',
        'port': 0,
        'reassembly_timeout': reassembly_timeout,
    })
    node.connect(sink)
    node.on_start()
    assert node.bound_port, "UdpInNode failed to bind (bound_port is falsy)"
    return node


def _make_out_node(target_port, chunk_size=None, encode_images=True, include_msg_props=False):
    """A started UdpOutNode targeting 127.0.0.1:target_port."""
    node = UdpOutNode(name='udp-out')
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
# Pure protocol unit tests (udp_protocol.py only - no sockets)
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
# Real loopback tests: UdpOutNode -> UDP -> UdpInNode
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


def test_include_msg_props_exact_replication(node_classes):
    """With include_msg_props on, the received message replicates the sent
    one - underscore props (_msgid, _timestamp_orig) included - and a
    non-JSON-serializable value skips just that key, not the whole message.

    (_timestamp_emit/_age/_queue_length are per-hop stamps rewritten by every
    PyNode send(), so only the stable identity props are compared exactly
    here; a Node-RED receiver gets ALL forwarded props verbatim.)
    """
    sink = node_classes['sink'](name='sink')
    in_node = _make_in_node(sink)
    out_node = _make_out_node(in_node.bound_port, include_msg_props=True)
    try:
        msg = out_node.create_message(payload=1784494826.7259126, frame_count=42)
        msg['drop_count'] = 3
        msg['not_serializable'] = object()  # must skip only this key
        sent_msgid = msg['_msgid']
        sent_ts_orig = msg['_timestamp_orig']
        out_node.on_input(msg)

        assert _wait_until(lambda: len(sink.received) == 1)
        received = sink.received[0]
        assert received['payload'] == 1784494826.7259126
        assert received['frame_count'] == 42
        assert received['drop_count'] == 3
        assert received['_msgid'] == sent_msgid
        assert received['_timestamp_orig'] == sent_ts_orig
        assert 'not_serializable' not in received
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
    """Hand-build a multi-chunk message and feed it to a real UdpInNode
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
        time.sleep(0.1 + UdpInNode._EVICT_INTERVAL + 0.4)

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
    out_node = UdpOutNode(name='udp-out')
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
# Example Node-RED interop flow JSON validation
# ===========================================================================

FLOW_JSON_PATH = (Path(__file__).resolve().parent.parent / 'pynode' / 'nodes' /
                  'SocketNode' / 'interop' / 'nodered-example-flow.json')


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
    func_src = {n['name']: n['func'] for n in data if n['type'] == 'function'
                and n['name'].startswith('PNB1')}
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


# ===========================================================================
# TCP/NDJSON transport (ndjson_protocol + TcpOutNode/TcpInNode)
# ===========================================================================

from pynode.nodes.SocketNode import ndjson_protocol as ndj  # noqa: E402
from pynode.nodes.SocketNode.tcp_in_node import TcpInNode  # noqa: E402
from pynode.nodes.SocketNode.tcp_out_node import TcpOutNode  # noqa: E402


def _make_tcp_in_node(sink):
    """A started TcpInNode on an ephemeral loopback port, wired to
    ``sink``. Caller must call ``.on_stop()`` (in a finally block)."""
    node = TcpInNode(name='tcp-in')
    node.configure({'bind_host': '127.0.0.1', 'port': 0})
    node.connect(sink)
    node.on_start()
    assert node.bound_port, "TcpInNode failed to bind"
    return node


def _make_tcp_out_node(target_port, **cfg_overrides):
    """A started TcpOutNode targeting 127.0.0.1:target_port, waited
    until connected. Caller must call ``.on_stop()`` (in a finally block)."""
    node = TcpOutNode(name='tcp-out')
    cfg = {'host': '127.0.0.1', 'port': target_port, 'reconnect_delay': 0.2}
    cfg.update(cfg_overrides)
    node.configure(cfg)
    node.on_start()
    assert _wait_until(lambda: node.connected), "tcp out never connected"
    return node


def test_ndjson_payload_encodings_pure():
    # plain JSON values pass through
    assert ndj.encode_payload({'a': 1}) == {'a': 1}
    assert ndj.decode_payload('hi') == 'hi'
    # bytes wrap to base64 marker and back
    wrapped = ndj.encode_payload(b'\x00\xffbin')
    assert wrapped[ndj.MARKER_KEY] == ndj.MARKER_BYTES
    assert ndj.decode_payload(wrapped) == b'\x00\xffbin'
    # ndarray (no jpeg) round-trips exactly
    arr = _make_test_frame()[:12, :16]  # small slice keeps base64 lines tiny
    wrapped = ndj.encode_payload(arr, encode_images=False)
    assert wrapped[ndj.MARKER_KEY] == ndj.MARKER_NDARRAY
    out = ndj.decode_payload(wrapped)
    assert out.dtype == arr.dtype and out.shape == arr.shape
    assert np.array_equal(out, arr)
    # jpeg marker decodes to an image of the same shape
    wrapped = ndj.encode_payload(arr, encode_images=True)
    assert wrapped[ndj.MARKER_KEY] == ndj.MARKER_JPEG
    assert ndj.decode_payload(wrapped).shape == arr.shape
    # non-serializable payload raises
    with pytest.raises(ndj.NdjsonError):
        ndj.encode_payload(object())


def test_ndjson_line_roundtrip_pure():
    msg = {'payload': {'v': 2}, 'topic': 't/a', '_msgid': 'abc',
           'frame_count': 9, 'bad': object()}
    line = ndj.build_line(msg, include_props=True)
    assert line.endswith(b'\n') and b'\n' not in line[:-1]
    payload, topic, extra = ndj.parse_line(line)
    assert payload == {'v': 2}
    assert topic == 't/a'
    assert extra == {'_msgid': 'abc', 'frame_count': 9}  # 'bad' skipped
    # a bare JSON value line is the payload itself
    payload, topic, extra = ndj.parse_line(b'123.5\n')
    assert payload == 123.5 and topic == '' and extra == {}


def test_tcp_roundtrip_json_real_nodes(node_classes):
    sink = node_classes['sink'](name='sink')
    in_node = _make_tcp_in_node(sink)
    out_node = _make_tcp_out_node(in_node.bound_port)
    try:
        out_node.on_input(out_node.create_message(payload={'v': 1}, topic='t'))
        assert _wait_until(lambda: len(sink.received) == 1)
        received = sink.received[0]
        assert received['payload'] == {'v': 1}
        assert received['topic'] == 't'
        assert out_node.sent_count == 1 and in_node.received_count == 1
    finally:
        out_node.on_stop()
        in_node.on_stop()


def test_tcp_exact_replication_real_nodes(node_classes):
    sink = node_classes['sink'](name='sink')
    in_node = _make_tcp_in_node(sink)
    out_node = _make_tcp_out_node(in_node.bound_port, include_msg_props=True)
    try:
        msg = out_node.create_message(payload=1784494826.7259126, frame_count=42)
        sent_msgid = msg['_msgid']
        sent_ts_orig = msg['_timestamp_orig']
        out_node.on_input(msg)
        assert _wait_until(lambda: len(sink.received) == 1)
        received = sink.received[0]
        assert received['payload'] == 1784494826.7259126
        assert received['frame_count'] == 42
        assert received['_msgid'] == sent_msgid
        assert received['_timestamp_orig'] == sent_ts_orig
    finally:
        out_node.on_stop()
        in_node.on_stop()


def test_tcp_frame_roundtrips_real_nodes(node_classes):
    sink = node_classes['sink'](name='sink')
    in_node = _make_tcp_in_node(sink)
    out_node = _make_tcp_out_node(in_node.bound_port, encode_images=False)
    try:
        frame = _make_test_frame()
        out_node.on_input(out_node.create_message(payload=frame))
        assert _wait_until(lambda: len(sink.received) == 1)
        assert np.array_equal(sink.received[0]['payload'], frame)  # raw = exact

        out_node.configure({'encode_images': True})
        out_node.on_input(out_node.create_message(payload=frame))
        assert _wait_until(lambda: len(sink.received) == 2)
        decoded = sink.received[1]['payload']
        assert decoded.shape == frame.shape
        diff = float(np.mean(np.abs(decoded.astype(np.int16) - frame.astype(np.int16))))
        assert diff < 5.0, f"JPEG round-trip mean abs diff too high: {diff}"
    finally:
        out_node.on_stop()
        in_node.on_stop()


def test_tcp_in_accepts_raw_client_lines(node_classes):
    """A plain socket sending split/bare/malformed lines: framing across
    packet boundaries works, a bare JSON value becomes the payload, and a
    malformed line is counted + skipped without killing the connection."""
    sink = node_classes['sink'](name='sink')
    in_node = _make_tcp_in_node(sink)
    client = socket.create_connection(('127.0.0.1', in_node.bound_port), timeout=5.0)
    try:
        # one line split across three sends
        line = json.dumps({'payload': {'n': 1}, 'topic': 'split'}).encode() + b'\n'
        for part in (line[:5], line[5:20], line[20:]):
            client.sendall(part)
            time.sleep(0.05)
        # malformed line, then a bare-value line, in one send
        client.sendall(b'{not json}\n"bare-string"\n')

        assert _wait_until(lambda: len(sink.received) == 2)
        assert sink.received[0]['payload'] == {'n': 1}
        assert sink.received[0]['topic'] == 'split'
        assert sink.received[1]['payload'] == 'bare-string'
        assert in_node.error_count == 1
    finally:
        client.close()
        in_node.on_stop()


def test_tcp_out_reconnects_after_server_restart(node_classes):
    sink = node_classes['sink'](name='sink')
    in_node = _make_tcp_in_node(sink)
    port = in_node.bound_port
    out_node = _make_tcp_out_node(port)
    try:
        out_node.on_input(out_node.create_message(payload={'n': 1}))
        assert _wait_until(lambda: len(sink.received) == 1)

        # Kill the server. A send right after the peer closes can still
        # succeed into the local TCP buffer, so keep poking until a send
        # errors and the node notices the connection is gone.
        in_node.on_stop()

        def _poke_until_disconnected():
            if out_node.connected:
                out_node.on_input(out_node.create_message(payload={'n': 'lost'}))
            return not out_node.connected
        assert _wait_until(_poke_until_disconnected, timeout=10.0, interval=0.1)

        # bring a server back on the SAME port and wait for reconnection
        sink2 = node_classes['sink'](name='sink2')
        in_node = TcpInNode(name='tcp-in-2')
        in_node.configure({'bind_host': '127.0.0.1', 'port': port})
        in_node.connect(sink2)
        in_node.on_start()
        assert in_node.bound_port == port
        assert _wait_until(lambda: out_node.connected)

        out_node.on_input(out_node.create_message(payload={'n': 2}))
        assert _wait_until(lambda: len(sink2.received) == 1)
        assert sink2.received[0]['payload'] == {'n': 2}
        assert out_node.dropped_count >= 1
    finally:
        out_node.on_stop()
        in_node.on_stop()


# ===========================================================================
# Copyable Node-RED flow snippets in the nodes' Info panels
# ===========================================================================

import html as _html  # noqa: E402

from pynode.nodes.SocketNode import nodered_snippets as ns  # noqa: E402

# PyNode node class -> (snippet kind, Node-RED node types the snippet must
# contain). The snippet is named for the PyNode node it pairs with, so e.g.
# 'udp_out' is the flow that *receives* from a UDP Out node.
SNIPPET_EXPECTATIONS = {
    UdpOutNode: ('udp_out', {'udp in', 'function', 'debug'}),
    UdpInNode: ('udp_in', {'inject', 'function', 'udp out'}),
    TcpOutNode: ('tcp_out', {'tcp in', 'json', 'function', 'debug'}),
    TcpInNode: ('tcp_in', {'inject', 'function', 'tcp out'}),
}


def _copy_blocks(info_html):
    """The decoded text of every Info.add_copy_block <pre> in ``info_html``.

    Mirrors what the frontend's copy button puts on the clipboard: the
    browser decodes the HTML entities, so the user pastes the original text.
    """
    return [_html.unescape(m) for m in
            re.findall(r'<pre class="info-copy-code">(.*?)</pre>', info_html, re.S)]


@pytest.mark.parametrize('kind,expected_types', [
    (kind, types) for kind, types in SNIPPET_EXPECTATIONS.values()
])
def test_nodered_snippet_is_an_importable_flow(kind, expected_types):
    """Each snippet must be a self-contained Node-RED flow: valid JSON, no
    dangling wires, and no 'z' tab reference (so Node-RED imports it onto
    whatever flow the user has open)."""
    nodes = json.loads(ns.flow_snippet(kind, 7999))

    assert isinstance(nodes, list) and nodes
    assert nodes[0]['type'] == 'comment', "snippet should lead with its how-to comment"
    assert '7999' in nodes[0]['info'], "comment must quote the port it was built for"

    ids = {n['id'] for n in nodes}
    assert len(ids) == len(nodes), "duplicate node ids in snippet"
    assert expected_types <= {n['type'] for n in nodes}

    for node in nodes:
        assert 'z' not in node, f"{node['id']} still references a flow tab"
        for port in (node.get('wires') or []):
            for target in port:
                assert target in ids, f"dangling wire target {target!r} in snippet {kind!r}"


def test_nodered_snippet_port_is_rewritten():
    """The transport node's port follows the PyNode node it is shown on, not
    the example flow's own port pairing."""
    for kind, _ in SNIPPET_EXPECTATIONS.values():
        nodes = json.loads(ns.flow_snippet(kind, 7999))
        transport = [n for n in nodes if n['type'] in ns._TRANSPORT_TYPES]
        assert len(transport) == 1, f"snippet {kind!r} must have exactly one transport node"
        assert transport[0]['port'] == '7999'


def test_nodered_snippet_js_is_sliced_from_the_example_flow():
    """Snippets must be *slices* of the example flow, not copies of it - that
    is what keeps the JS a user copies from the Info panel in lockstep with
    the JS the parity tests above check against udp_protocol.py."""
    flow_funcs = {n['id']: n['func'] for n in _load_flow() if n['type'] == 'function'}
    assert flow_funcs

    seen = 0
    for kind, _ in SNIPPET_EXPECTATIONS.values():
        for node in json.loads(ns.flow_snippet(kind, 7999)):
            if node['type'] == 'function':
                assert node['id'] in flow_funcs, f"{kind!r} has a function node not in the example flow"
                assert node['func'] == flow_funcs[node['id']]
                seen += 1
    assert seen >= 4, "expected every snippet to carry its example-flow function node"


def test_node_info_offers_a_copyable_nodered_flow():
    """Every socket node's Info panel carries exactly one copy block, and it
    holds a valid flow whose port matches that node's default Port - so a
    user who copies it and leaves both ends at their defaults is wired up."""
    for node_class, (kind, expected_types) in SNIPPET_EXPECTATIONS.items():
        blocks = _copy_blocks(node_class.info)
        assert len(blocks) == 1, f"{node_class.__name__} should have one copy block"

        nodes = json.loads(blocks[0])  # raises if the escaping round-trip broke
        assert expected_types <= {n['type'] for n in nodes}

        transport = next(n for n in nodes if n['type'] in ns._TRANSPORT_TYPES)
        assert transport['port'] == str(node_class.DEFAULT_CONFIG['port']), (
            f"{node_class.__name__}'s snippet port must match its default Port")


def test_node_properties_point_at_the_info_panel():
    """Users do not read READMEs and rarely open the Info tab unprompted, so
    each socket node ends its properties with a hint that points there."""
    for node_class in SNIPPET_EXPECTATIONS:
        hints = [p for p in node_class.properties if p.get('type') == 'hint']
        assert len(hints) == 1, f"{node_class.__name__} should have one hint property"
        assert hints[0]['label'], "hint needs visible text"
        assert hints[0].get('button'), "hint needs the button that opens the Info panel"
        assert node_class.properties[-1] is hints[0], "the hint belongs at the end"


def _unterminated_string_lines(js_src):
    """Report JS string literals left open at the end of their line.

    A JSON-escaping slip - writing "\n" in the flow file where "\\n" was
    meant - turns an intended escape sequence into a real newline inside a
    '...' or "..." literal. JavaScript rejects that with "Invalid or
    unexpected token", but only when Node-RED compiles the function node,
    long after every Python test has passed. Template literals may legally
    span lines and are skipped; comments are skipped so apostrophes in prose
    do not trip this.
    """
    offenders = []
    quote = None          # the active ' or " (None when not inside one)
    comment = None        # 'line' or 'block'
    in_template = False
    escaped = False

    for lineno, line in enumerate(js_src.split('\n'), 1):
        if comment == 'line':
            comment = None
        i = 0
        while i < len(line):
            ch = line[i]
            if comment == 'block':
                if line[i:i + 2] == '*/':
                    comment = None
                    i += 1
            elif quote or in_template:
                if escaped:
                    escaped = False
                elif ch == '\\':
                    escaped = True
                elif in_template and ch == '`':
                    in_template = False
                elif ch == quote:
                    quote = None
            elif line[i:i + 2] == '//':
                break
            elif line[i:i + 2] == '/*':
                comment = 'block'
                i += 1
            elif ch in ('"', "'"):
                quote = ch
            elif ch == '`':
                in_template = True
            i += 1
        if quote:
            offenders.append((lineno, line))
            quote = None  # report once per line, then keep scanning
        escaped = False
    return offenders


def test_flow_json_function_string_literals_are_well_formed():
    """Regression: 'NDJSON stringify' once shipped a raw newline inside its
    "\\n" literal, so Node-RED refused to compile the node at all."""
    checked = 0
    for node in _load_flow():
        if node['type'] != 'function':
            continue
        offenders = _unterminated_string_lines(node['func'])
        assert not offenders, (
            f"{node['name']!r} has a string literal running off the end of a "
            f"line - Node-RED will not compile it: {offenders}")
        checked += 1
    assert checked >= 4, "expected every function node to be checked"


def test_unterminated_string_detector_catches_the_original_bug():
    """Guard the guard: the exact source that broke in Node-RED must fail."""
    broken = 'msg.payload = JSON.stringify({a: 1}) + "\n";\nreturn msg;\n'
    assert _unterminated_string_lines(broken)

    fixed = 'msg.payload = JSON.stringify({a: 1}) + "\\n";\nreturn msg;\n'
    assert not _unterminated_string_lines(fixed)

    # Prose apostrophes in comments are not string literals.
    assert not _unterminated_string_lines("// wire this node's output onward\n")


def test_nodered_sender_appends_the_ndjson_line_terminator():
    """The Node-RED -> PyNode sender must append the newline: TcpInNode only
    emits once it sees b'\\n', so a sender that drops it leaves the
    connection up (Node-RED shows 'Connected') and PyNode silently buffering."""
    stringify = next(n['func'] for n in _load_flow()
                     if n['type'] == 'function' and n.get('name') == 'NDJSON stringify')

    assert '"\\n"' in stringify or "'\\n'" in stringify, (
        "NDJSON stringify must append the two-character \\n escape")
    assert not _unterminated_string_lines(stringify)

    # What it emits must parse as a line on the PyNode side.
    produced = json.dumps({'payload': {'hello': 'from node-red'}, 'topic': 't'}) + '\n'
    assert produced.endswith('\n'), "no terminator means TcpInNode never emits"
    payload, topic, _ = ndj.parse_line(produced.encode().rstrip(b'\n'))
    assert payload == {'hello': 'from node-red'}
    assert topic == 't'


def test_nodered_snippet_carries_the_fixed_stringify_function():
    """The copyable snippet is sliced from the flow, so the fix must reach the
    Info panel too - that is where users now get this code from."""
    nodes = json.loads(ns.flow_snippet('tcp_in', 7404))
    stringify = next(n for n in nodes if n['type'] == 'function')
    assert not _unterminated_string_lines(stringify['func'])
    assert '"\\n"' in stringify['func']


# ===========================================================================
# Execute the shipped Node-RED JavaScript against the real nodes
#
# The flow file's function nodes are JavaScript no Python test can otherwise
# exercise: a syntax error or a framing slip in them surfaces only when a
# user pastes the flow (or an Info-panel snippet) into Node-RED. These tests
# run that exact source under Node and wire its output into a live PyNode
# node, proving both directions of the bridge end to end. Skipped when
# node(1) is not installed.
# ===========================================================================

import base64  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

NODE_BIN = shutil.which('node')
requires_node = pytest.mark.skipif(
    NODE_BIN is None, reason="node(1) not installed; cannot run the Node-RED JS")

# Shims for the globals Node-RED injects into a function node.
_NODE_RED_PRELUDE = """
const node = { warn: () => {}, error: () => {}, log: () => {}, send: () => {} };
const __store = {};
const context = { get: (k) => __store[k], set: (k, v) => { __store[k] = v; } };
const flow = context, global = context;
"""


def _flow_function_source(name):
    return next(n['func'] for n in _load_flow()
                if n['type'] == 'function' and n.get('name') == name)


def _run_node(script):
    """Run a JS script under Node and JSON-parse what it writes to stdout."""
    with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
        f.write(script)
        path = f.name
    try:
        result = subprocess.run([NODE_BIN, path], capture_output=True, text=True, timeout=30)
    finally:
        os.unlink(path)
    assert result.returncode == 0, (
        f"the shipped Node-RED JavaScript failed to run:\n{result.stderr}")
    return json.loads(result.stdout)


def _run_nodered_function(func_name, msg, emit):
    """Run one function node's body over ``msg``; ``emit`` is a JS expression
    over its return value ``out``."""
    return _run_node(
        _NODE_RED_PRELUDE
        + "function nrFunction(msg) {\n%s\n}\n" % _flow_function_source(func_name)
        + "const out = nrFunction(%s);\n" % json.dumps(msg)
        + "process.stdout.write(JSON.stringify(%s));\n" % emit)


@requires_node
def test_nodered_ndjson_stringify_output_is_accepted_by_tcp_in(node_classes):
    """Run the flow's 'NDJSON stringify' JS for real and push exactly what it
    produces down a socket into a live TcpInNode.

    Regression for a bug hit in Node-RED: the function would not compile
    ("Invalid or unexpected token" - a raw newline inside its "\\n" literal),
    and deleting the newline to silence that left the line unterminated, so
    the socket connects (Node-RED shows 'Connected') but TcpInNode buffers
    forever and emits nothing.
    """
    wire_text = _run_nodered_function(
        'NDJSON stringify',
        {'payload': {'hello': 'from node-red over tcp'}, 'topic': 'nodered/tcp/demo'},
        'out.payload')

    assert wire_text.endswith('\n'), (
        "the Node-RED sender must terminate its line or TcpInNode never emits")

    sink = node_classes['sink'](name='sink')
    in_node = _make_tcp_in_node(sink)
    client = socket.create_connection(('127.0.0.1', in_node.bound_port), timeout=5.0)
    try:
        client.sendall(wire_text.encode('utf-8'))
        assert _wait_until(lambda: len(sink.received) == 1), (
            "TcpInNode emitted nothing for the Node-RED sender's output")
        assert sink.received[0]['payload'] == {'hello': 'from node-red over tcp'}
        assert sink.received[0]['topic'] == 'nodered/tcp/demo'
    finally:
        client.close()
        in_node.on_stop()


@requires_node
def test_nodered_pnb1_chunk_send_datagrams_are_accepted_by_udp_in(node_classes):
    """The UDP send direction: run the flow's 'PNB1 chunk+send' JS and deliver
    its datagrams, byte for byte, to a live UdpInNode."""
    # The function ends `return [datagrams.map(...)]`: one output port,
    # carrying an array of messages, so the datagrams are at out[0].
    datagrams = _run_nodered_function(
        'PNB1 chunk+send',
        {'payload': {'hello': 'from node-red'}, 'topic': 'nodered/bridge/demo'},
        'out[0].map(m => m.payload.toString("base64"))')
    assert datagrams, "chunk+send produced no datagrams"

    sink = node_classes['sink'](name='sink')
    in_node = _make_in_node(sink)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for chunk in datagrams:
            sender.sendto(base64.b64decode(chunk), ('127.0.0.1', in_node.bound_port))
        assert _wait_until(lambda: len(sink.received) == 1), (
            "UdpInNode emitted nothing for the Node-RED sender's datagrams")
        assert sink.received[0]['payload'] == {'hello': 'from node-red'}
        assert sink.received[0]['topic'] == 'nodered/bridge/demo'
    finally:
        sender.close()
        in_node.on_stop()


@requires_node
def test_nodered_pnb1_reassemble_decodes_what_udp_out_sends():
    """The UDP receive direction: capture real datagrams off a UdpOutNode and
    let the flow's 'PNB1 reassemble' JS decode them, one datagram per call
    with its context carried across, exactly as Node-RED drives it."""
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(('127.0.0.1', 0))
    receiver.settimeout(2.0)
    port = receiver.getsockname()[1]

    out_node = _make_out_node(port, chunk_size=1400)
    try:
        # Big enough to need several chunks, so reassembly is exercised.
        out_node.on_input(out_node.create_message(
            payload={'detections': [{'i': i, 'label': 'person'} for i in range(200)]},
            topic='pynode/detections'))
        captured = []
        while True:
            try:
                data, _ = receiver.recvfrom(65535)
            except socket.timeout:
                break
            captured.append(base64.b64encode(data).decode('ascii'))
    finally:
        out_node.on_stop()
        receiver.close()

    assert len(captured) > 1, "expected a multi-chunk message to reassemble"

    emitted = _run_node(
        _NODE_RED_PRELUDE
        + "function nrFunction(msg) {\n%s\n}\n" % _flow_function_source('PNB1 reassemble')
        + "const datagrams = %s;\n" % json.dumps(captured)
        + """
const out = [];
for (const b64 of datagrams) {
    const msg = { payload: Buffer.from(b64, 'base64'), ip: '127.0.0.1', port: 40000 };
    const result = nrFunction(msg);
    if (result) { out.push({ topic: result.topic, payload: result.payload }); }
}
process.stdout.write(JSON.stringify(out));
""")

    assert len(emitted) == 1, (
        f"PNB1 reassemble should emit exactly one message, got {len(emitted)}")
    assert emitted[0]['topic'] == 'pynode/detections'
    assert emitted[0]['payload']['detections'][0] == {'i': 0, 'label': 'person'}
    assert len(emitted[0]['payload']['detections']) == 200
