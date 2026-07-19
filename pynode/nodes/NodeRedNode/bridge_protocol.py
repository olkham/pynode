"""Wire protocol for the PyNode <-> Node-RED UDP bridge.

This module is intentionally **pure** - no sockets, no threads, no node
classes. It only builds/parses datagrams and reassembles fragmented
messages from raw bytes. That keeps it trivially unit-testable and lets
both ``NodeRedOutNode``/``NodeRedInNode`` and ``tests/test_nodered_bridge.py``
share exactly one implementation of the byte layout, instead of the tests
re-deriving it (and silently drifting from what the nodes actually send).

The Node-RED side (``nodered/pynode-bridge-flow.json``) re-implements this
same layout in plain JavaScript inside two function nodes. See that folder's
README for the JS mirror and ``tests/test_nodered_bridge.py`` for a check
that the constants embedded in the JS match the constants below.

Wire format
-----------
Every UDP datagram is a fixed 16-byte header followed by a body::

    offset  size  field          struct  meaning
    0       4     magic          4s      b'PNB1'
    4       1     version        B       header version (currently 1)
    5       1     flags          B       bit0 = payload is binary
                                          bit1 = payload is a JPEG image
    6       4     message_id     I       monotonically increasing per sender,
                                          wraps at 2**32
    10      2     chunk_index    H       0-based index of this datagram
    12      2     chunk_count    H       total datagrams for this message
    14      2     meta_length    H       bytes of JSON metadata in THIS
                                          datagram's body (only nonzero for
                                          chunk_index == 0)

Chunk 0's body is ``meta_length`` bytes of UTF-8 JSON metadata, immediately
followed by the first slice of payload bytes. Chunks 1..N-1's body is a raw
continuation of the payload (no metadata). Concatenating the payload slices
of every chunk, in chunk_index order, reproduces the full payload bytes.

Metadata JSON (chunk 0 only)::

    {
        "payload_type": "json" | "bytes" | "jpeg" | "raw_numpy",
        "total_size": <int, total payload bytes across all chunks>,
        "topic": "<str>",              # omitted if empty
        "extra": {...},                # omitted if not requested/empty -
                                        # non-underscore msg properties other
                                        # than payload/topic, forwarded
                                        # verbatim when the sending node has
                                        # "include msg props" enabled
        "dtype": "<numpy dtype str>",  # raw_numpy only
        "shape": [h, w, ...]           # raw_numpy only
    }

Payload encodings
------------------
* dict / list / str / number / bool / None -> UTF-8 JSON bytes (``json``).
* bytes / bytearray -> sent as-is (``bytes``).
* numpy uint8 array shaped like an image (HxW or HxWxC, C in 1/3/4) with
  image encoding requested -> JPEG-encoded via ``cv2.imencode`` (``jpeg``).
* any other numpy array, or an image array with image encoding turned off ->
  raw bytes (``arr.tobytes()``) plus ``dtype``/``shape`` in the metadata so
  the receiver can reconstruct it with ``numpy.frombuffer(...).reshape(...)``
  (``raw_numpy``). This path exists mainly for PyNode<->PyNode use (or a
  Node-RED flow that just wants the raw bytes) since Node-RED has no numpy.
"""

from __future__ import annotations

import json
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import cv2

# --------------------------------------------------------------------------
# Wire constants
# --------------------------------------------------------------------------

MAGIC = b'PNB1'
HEADER_VERSION = 1
HEADER_FORMAT = '>4sBBIHHH'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 16 bytes
assert HEADER_SIZE == 16

FLAG_BINARY = 0x01
FLAG_JPEG = 0x02

# Body bytes per datagram (excludes the 16-byte header). 60000 + 16 = 60016,
# comfortably under the 65507-byte practical max UDP payload for IPv4.
DEFAULT_CHUNK_SIZE = 60000
# Safe for networks with a conservative MTU / NAT path (WAN/VPN links).
MTU_CHUNK_SIZE = 1400
CHUNK_SIZE_OPTIONS = (DEFAULT_CHUNK_SIZE, MTU_CHUNK_SIZE)

DEFAULT_REASSEMBLY_TIMEOUT = 2.0  # seconds
DEFAULT_MAX_INCOMPLETE = 100  # pending (addr, message_id) buffers

MAX_MESSAGE_ID = 0xFFFFFFFF  # 32-bit unsigned wraparound
MAX_CHUNK_COUNT = 0xFFFF  # 16-bit unsigned

DEFAULT_JPEG_QUALITY = 80


class PayloadType:
    """String constants used in the ``payload_type`` metadata field."""
    JSON = 'json'
    BYTES = 'bytes'
    JPEG = 'jpeg'
    RAW_NUMPY = 'raw_numpy'


class BridgeError(Exception):
    """Base class for bridge protocol errors."""


class EncodeError(BridgeError):
    """Raised when a message cannot be encoded into datagrams."""


class DecodeError(BridgeError):
    """Raised when a datagram/payload cannot be decoded."""


# --------------------------------------------------------------------------
# Header pack/unpack
# --------------------------------------------------------------------------

class DatagramHeader:
    """Parsed fixed-size header of one datagram."""

    __slots__ = ('version', 'flags', 'message_id', 'chunk_index', 'chunk_count', 'meta_length')

    def __init__(self, version: int, flags: int, message_id: int,
                 chunk_index: int, chunk_count: int, meta_length: int):
        self.version = version
        self.flags = flags
        self.message_id = message_id
        self.chunk_index = chunk_index
        self.chunk_count = chunk_count
        self.meta_length = meta_length

    @property
    def is_binary(self) -> bool:
        return bool(self.flags & FLAG_BINARY)

    @property
    def is_jpeg(self) -> bool:
        return bool(self.flags & FLAG_JPEG)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"DatagramHeader(version={self.version}, flags={self.flags}, "
                f"message_id={self.message_id}, chunk_index={self.chunk_index}, "
                f"chunk_count={self.chunk_count}, meta_length={self.meta_length})")


def pack_header(flags: int, message_id: int, chunk_index: int, chunk_count: int,
                meta_length: int, version: int = HEADER_VERSION) -> bytes:
    """Pack a 16-byte header. Raises ``EncodeError`` if any field overflows."""
    try:
        return struct.pack(HEADER_FORMAT, MAGIC, version, flags,
                           message_id & MAX_MESSAGE_ID, chunk_index, chunk_count, meta_length)
    except struct.error as exc:
        raise EncodeError(f"Failed to pack datagram header: {exc}") from exc


def unpack_header(data: bytes) -> DatagramHeader:
    """Parse and validate the header of a received datagram.

    Raises ``DecodeError`` if the datagram is too short, the magic doesn't
    match, or the header version is newer than this module understands.
    """
    if len(data) < HEADER_SIZE:
        raise DecodeError(f"Datagram too short: {len(data)} bytes (need >= {HEADER_SIZE})")
    magic, version, flags, message_id, chunk_index, chunk_count, meta_length = \
        struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    if magic != MAGIC:
        raise DecodeError(f"Bad magic: {magic!r} (expected {MAGIC!r})")
    if chunk_count == 0 or chunk_index >= chunk_count:
        raise DecodeError(f"Invalid chunk index/count: {chunk_index}/{chunk_count}")
    return DatagramHeader(version, flags, message_id, chunk_index, chunk_count, meta_length)


def next_message_id(current: int) -> int:
    """Return the next message id, wrapping at 2**32 back to 0."""
    return (current + 1) & MAX_MESSAGE_ID


# --------------------------------------------------------------------------
# Payload encode / decode
# --------------------------------------------------------------------------

def _is_image_like(arr: 'np.ndarray') -> bool:
    """True if a numpy array looks like something cv2.imencode can handle."""
    if arr.dtype != np.uint8:
        return False
    if arr.ndim == 2:
        return True
    if arr.ndim == 3 and arr.shape[2] in (1, 3, 4):
        return True
    return False


def _classify_payload(payload: Any, encode_images: bool, jpeg_quality: int
                       ) -> Tuple[str, bytes, Dict[str, Any], int]:
    """Turn a message payload into (payload_type, payload_bytes, extra_meta, flags).

    ``extra_meta`` holds payload-type-specific metadata fields (currently
    only ``dtype``/``shape`` for ``raw_numpy``) to be merged into the
    datagram's metadata JSON.
    """
    if isinstance(payload, (bytes, bytearray)):
        return PayloadType.BYTES, bytes(payload), {}, FLAG_BINARY

    if isinstance(payload, np.ndarray):
        if encode_images and _is_image_like(payload):
            ok, buf = cv2.imencode('.jpg', payload,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
            if not ok:
                raise EncodeError("cv2.imencode failed to encode image payload as JPEG")
            return PayloadType.JPEG, buf.tobytes(), {}, FLAG_BINARY | FLAG_JPEG

        arr = np.ascontiguousarray(payload)
        extra_meta = {'dtype': str(arr.dtype), 'shape': list(arr.shape)}
        return PayloadType.RAW_NUMPY, arr.tobytes(), extra_meta, FLAG_BINARY

    # Fall through to JSON for dict / list / str / int / float / bool / None.
    try:
        payload_bytes = json.dumps(payload).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise EncodeError(f"Unsupported payload type for bridge: {type(payload).__name__} ({exc})") from exc
    return PayloadType.JSON, payload_bytes, {}, 0


def decode_payload(payload_type: str, data: bytes, meta: Dict[str, Any]) -> Any:
    """Reverse of ``_classify_payload`` given the reassembled payload bytes."""
    if payload_type == PayloadType.JSON:
        if not data:
            return None
        try:
            return json.loads(data.decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as exc:
            raise DecodeError(f"Failed to decode JSON payload: {exc}") from exc

    if payload_type == PayloadType.BYTES:
        return bytes(data)

    if payload_type == PayloadType.JPEG:
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise DecodeError("cv2.imdecode failed to decode JPEG payload")
        return img

    if payload_type == PayloadType.RAW_NUMPY:
        dtype = meta.get('dtype')
        shape = meta.get('shape')
        if not dtype or shape is None:
            raise DecodeError("raw_numpy payload missing dtype/shape metadata")
        try:
            # .copy() -> a fresh, independent, writable buffer per message
            # (np.frombuffer otherwise returns a read-only view onto `data`,
            # which is about to be discarded/reused by the caller).
            arr = np.frombuffer(data, dtype=np.dtype(dtype)).copy()
            arr = arr.reshape(shape)
        except (TypeError, ValueError) as exc:
            raise DecodeError(f"Failed to reconstruct raw_numpy payload: {exc}") from exc
        return arr

    raise DecodeError(f"Unknown payload_type: {payload_type!r}")


# --------------------------------------------------------------------------
# Datagram construction
# --------------------------------------------------------------------------

def build_datagrams(message_id: int, topic: str, payload: Any, *,
                     extra_props: Optional[Dict[str, Any]] = None,
                     chunk_size: int = DEFAULT_CHUNK_SIZE,
                     encode_images: bool = True,
                     jpeg_quality: int = DEFAULT_JPEG_QUALITY) -> List[bytes]:
    """Build the full list of UDP datagrams (header+body, ready to sendto) for one message.

    Args:
        message_id: This sender's message id (already wrapped to 32 bits by
            the caller, e.g. via ``next_message_id``).
        topic: Message topic, or '' for none.
        payload: The message payload; see the module docstring for supported
            types.
        extra_props: Optional dict of additional message properties to
            forward in the metadata (only non-underscore, non payload/topic
            keys should be passed in here - filtering is the caller's job).
        chunk_size: Max body bytes per datagram (excludes the 16-byte
            header). Use ``MTU_CHUNK_SIZE`` for WAN links.
        encode_images: Whether numpy image-like arrays should be JPEG
            encoded (True) or sent raw with dtype/shape metadata (False).
        jpeg_quality: JPEG quality (1-100) when JPEG-encoding an image.

    Returns:
        List of complete datagram byte strings in send order.

    Raises:
        EncodeError: unsupported payload type, metadata too large to fit in
            one chunk, or the message needs more than 65535 chunks.
    """
    if chunk_size <= 0:
        raise EncodeError(f"chunk_size must be positive, got {chunk_size}")

    payload_type, payload_bytes, extra_meta, flags = _classify_payload(
        payload, encode_images, jpeg_quality)

    meta: Dict[str, Any] = {
        'payload_type': payload_type,
        'total_size': len(payload_bytes),
    }
    if topic:
        meta['topic'] = topic
    if extra_props:
        meta['extra'] = extra_props
    meta.update(extra_meta)

    try:
        meta_bytes = json.dumps(meta, separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise EncodeError(f"Failed to encode metadata (non-JSON-safe extra props?): {exc}") from exc

    if len(meta_bytes) > 0xFFFF:
        raise EncodeError(f"Metadata too large: {len(meta_bytes)} bytes (max 65535)")
    first_capacity = chunk_size - len(meta_bytes)
    if first_capacity < 0:
        raise EncodeError(
            f"Metadata ({len(meta_bytes)} bytes) does not fit within chunk_size ({chunk_size}); "
            "increase chunk_size or reduce topic/extra props")

    chunk0_payload = payload_bytes[:first_capacity]
    rest = payload_bytes[first_capacity:]
    rest_chunks = [rest[i:i + chunk_size] for i in range(0, len(rest), chunk_size)] if rest else []
    chunk_count = 1 + len(rest_chunks)
    if chunk_count > MAX_CHUNK_COUNT:
        raise EncodeError(f"Message too large: {chunk_count} chunks exceeds max {MAX_CHUNK_COUNT}")

    datagrams: List[bytes] = []
    header0 = pack_header(flags, message_id, 0, chunk_count, len(meta_bytes))
    datagrams.append(header0 + meta_bytes + chunk0_payload)
    for idx, chunk in enumerate(rest_chunks, start=1):
        header = pack_header(flags, message_id, idx, chunk_count, 0)
        datagrams.append(header + chunk)
    return datagrams


# --------------------------------------------------------------------------
# Reassembly
# --------------------------------------------------------------------------

class _PendingMessage:
    """Chunks received so far for one (sender_addr, message_id)."""

    __slots__ = ('chunk_count', 'flags', 'chunks', 'meta', 'first_seen')

    def __init__(self, chunk_count: int, flags: int, now: float):
        self.chunk_count = chunk_count
        self.flags = flags
        self.chunks: Dict[int, bytes] = {}
        self.meta: Optional[Dict[str, Any]] = None
        self.first_seen = now

    @property
    def is_complete(self) -> bool:
        return len(self.chunks) >= self.chunk_count and \
            all(i in self.chunks for i in range(self.chunk_count))


class Reassembler:
    """Buffers and reassembles fragmented messages from raw datagrams.

    Pure logic keyed by ``(sender_addr, message_id)`` - no socket I/O.
    Thread-safe: a receiver thread can call :meth:`add_datagram` /
    :meth:`evict_stale` while the ``pending``/``stats`` attributes are
    inspected from another thread (e.g. a test, after joining the thread).

    Incomplete buffers are dropped either when they exceed ``timeout``
    seconds old (call :meth:`evict_stale` periodically - the receiving node
    does this on its poll loop) or when the number of pending buffers
    exceeds ``max_incomplete`` (oldest is evicted immediately to bound
    memory under a flood of never-completing messages).
    """

    def __init__(self, timeout: float = DEFAULT_REASSEMBLY_TIMEOUT,
                 max_incomplete: int = DEFAULT_MAX_INCOMPLETE):
        self.timeout = timeout
        self.max_incomplete = max_incomplete
        self.pending: Dict[Tuple[Any, int], _PendingMessage] = {}
        self.stats: Dict[str, int] = {
            'received_datagrams': 0,
            'completed': 0,
            'dropped_timeout': 0,
            'dropped_overflow': 0,
            'decode_errors': 0,
            'duplicate_chunks': 0,
        }
        self._lock = threading.Lock()

    def _evict_oldest_locked(self):
        if not self.pending:
            return
        oldest_key = min(self.pending, key=lambda k: self.pending[k].first_seen)
        del self.pending[oldest_key]
        self.stats['dropped_overflow'] += 1

    def add_datagram(self, addr: Any, data: bytes, now: Optional[float] = None
                      ) -> Optional[Dict[str, Any]]:
        """Feed one received datagram in. Returns the completed message dict
        (``{'addr', 'message_id', 'meta', 'payload_bytes', 'flags'}``) once
        every chunk for its (addr, message_id) has arrived, else ``None``.
        """
        if now is None:
            now = time.time()
        try:
            header = unpack_header(data)
        except DecodeError:
            with self._lock:
                self.stats['decode_errors'] += 1
            return None

        body = data[HEADER_SIZE:]
        key = (addr, header.message_id)
        with self._lock:
            self.stats['received_datagrams'] += 1
            pending = self.pending.get(key)
            if pending is None:
                if len(self.pending) >= self.max_incomplete:
                    self._evict_oldest_locked()
                pending = _PendingMessage(header.chunk_count, header.flags, now)
                self.pending[key] = pending

            if header.chunk_index in pending.chunks:
                self.stats['duplicate_chunks'] += 1

            if header.chunk_index == 0:
                meta_bytes = body[:header.meta_length]
                try:
                    pending.meta = json.loads(meta_bytes.decode('utf-8'))
                except (UnicodeDecodeError, ValueError):
                    self.stats['decode_errors'] += 1
                    del self.pending[key]
                    return None
                pending.chunks[0] = body[header.meta_length:]
            else:
                pending.chunks[header.chunk_index] = body

            if not pending.is_complete:
                return None

            del self.pending[key]
            self.stats['completed'] += 1
            payload_bytes = b''.join(pending.chunks[i] for i in range(pending.chunk_count))
            return {
                'addr': addr,
                'message_id': header.message_id,
                'meta': pending.meta or {},
                'payload_bytes': payload_bytes,
                'flags': pending.flags,
            }

    def evict_stale(self, now: Optional[float] = None) -> int:
        """Drop pending buffers older than ``self.timeout``. Returns count evicted."""
        if now is None:
            now = time.time()
        with self._lock:
            stale_keys = [k for k, v in self.pending.items() if now - v.first_seen > self.timeout]
            for k in stale_keys:
                del self.pending[k]
            self.stats['dropped_timeout'] += len(stale_keys)
            return len(stale_keys)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self.pending)
