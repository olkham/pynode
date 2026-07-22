"""Newline-delimited-JSON (NDJSON) framing for the TCP messaging nodes.

One message = one JSON object on one line, terminated by ``\n``. This is the
"simple" counterpart to the chunked-UDP ``udp_protocol``: TCP already
provides ordering, reliability and unlimited message size, so the only
framing needed is the newline (``json.dumps`` escapes any newline inside
string values, so a raw ``\n`` can never appear inside a line).

A consumer needs NO custom framing code: read the stream, split on ``\n``,
JSON.parse each line. (A Node-RED ``tcp in`` node in "stream of strings,
delimited by \\n" mode feeding a ``json`` node does exactly this.)

Line shape
----------
``{"payload": <encoded>, "topic": "...", ...extra props...}`` - ``topic`` is
omitted when empty; extra props (underscore ones included) are present when
the sender forwards them. A line that parses to anything OTHER than an
object with a ``"payload"`` key is treated as a bare payload (convenient
when a sender emits a plain JSON value per line).

Binary payloads
---------------
JSON has no bytes type, so non-JSON payloads are wrapped in a marker object
(key ``"_pnb"``) with base64 data:

* numpy image + encode_images -> ``{"_pnb": "jpeg", "data": <b64>}``
* numpy array (no encode)     -> ``{"_pnb": "ndarray", "dtype": ..., "shape":
  [...], "data": <b64 raw bytes>}``
* bytes/bytearray             -> ``{"_pnb": "bytes", "data": <b64>}``

A receiving ``TcpInNode`` unwraps these back to numpy/bytes. A non-Python
consumer sees plain objects; decode where needed (e.g. in JavaScript,
``Buffer.from(obj.data, 'base64')``). Base64 costs ~33% size overhead - for
sustained high-rate video frames prefer the UDP (PNB1) nodes, which send
binary natively.
"""

import base64
import json
from typing import Any, Dict, Tuple

MARKER_KEY = '_pnb'
MARKER_JPEG = 'jpeg'
MARKER_NDARRAY = 'ndarray'
MARKER_BYTES = 'bytes'

DEFAULT_JPEG_QUALITY = 80


class NdjsonError(Exception):
    """Raised when a payload cannot be encoded or a line cannot be decoded."""


def encode_payload(payload: Any, encode_images: bool = True,
                   jpeg_quality: int = DEFAULT_JPEG_QUALITY) -> Any:
    """Return a JSON-serializable representation of ``payload``.

    numpy arrays and bytes become base64 marker objects (see module
    docstring); everything already JSON-serializable passes through as-is.

    Raises:
        NdjsonError: when the payload is neither JSON-serializable nor a
            supported binary type.
    """
    import numpy as np

    if isinstance(payload, np.ndarray):
        if encode_images:
            import cv2
            ok, buf = cv2.imencode(
                '.jpg', payload, [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)])
            if not ok:
                raise NdjsonError(
                    "cv2.imencode failed - payload is a numpy array that is "
                    "not an encodable image; uncheck Encode Images to send "
                    "it as raw ndarray data")
            return {MARKER_KEY: MARKER_JPEG,
                    'data': base64.b64encode(buf.tobytes()).decode('ascii')}
        return {MARKER_KEY: MARKER_NDARRAY,
                'dtype': str(payload.dtype),
                'shape': list(payload.shape),
                'data': base64.b64encode(payload.tobytes()).decode('ascii')}

    if isinstance(payload, (bytes, bytearray, memoryview)):
        return {MARKER_KEY: MARKER_BYTES,
                'data': base64.b64encode(bytes(payload)).decode('ascii')}

    try:
        json.dumps(payload)
    except (TypeError, ValueError) as e:
        raise NdjsonError(f"payload is not JSON-serializable: {e}") from e
    return payload


def decode_payload(obj: Any) -> Any:
    """Reverse :func:`encode_payload` - unwrap marker objects, pass the rest.

    A malformed marker object (bad base64, unknown marker, missing fields)
    raises :class:`NdjsonError`; a plain value comes back unchanged.
    """
    if not (isinstance(obj, dict) and MARKER_KEY in obj):
        return obj

    marker = obj.get(MARKER_KEY)
    try:
        raw = base64.b64decode(obj['data'], validate=True)
    except (KeyError, ValueError, TypeError) as e:
        raise NdjsonError(f"bad {marker!r} marker object: {e}") from e

    if marker == MARKER_JPEG:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise NdjsonError("jpeg marker data did not decode to an image")
        return img
    if marker == MARKER_NDARRAY:
        import numpy as np
        try:
            return np.frombuffer(raw, dtype=obj['dtype']).reshape(obj['shape']).copy()
        except (KeyError, TypeError, ValueError) as e:
            raise NdjsonError(f"bad ndarray marker object: {e}") from e
    if marker == MARKER_BYTES:
        return raw
    raise NdjsonError(f"unknown {MARKER_KEY} marker: {marker!r}")


def build_line(msg: Dict[str, Any], include_props: bool = False,
               encode_images: bool = True,
               jpeg_quality: int = DEFAULT_JPEG_QUALITY) -> bytes:
    """Serialize a PyNode message dict to one NDJSON line (bytes incl ``\\n``).

    ``payload``/``topic`` always travel; with ``include_props`` every other
    property (underscore ones included) is added too, skipping individual
    values that are not JSON-serializable - mirroring the UDP node's
    exact-replication semantics.
    """
    obj: Dict[str, Any] = {
        'payload': encode_payload(msg.get('payload'), encode_images, jpeg_quality)
    }
    topic = msg.get('topic', '') or ''
    if topic:
        obj['topic'] = topic
    if include_props:
        for k, v in msg.items():
            if k in ('payload', 'topic'):
                continue
            try:
                json.dumps(v)
            except (TypeError, ValueError):
                continue
            obj[k] = v
    return json.dumps(obj, separators=(',', ':')).encode('utf-8') + b'\n'


def parse_line(line: bytes) -> Tuple[Any, str, Dict[str, Any]]:
    """Parse one NDJSON line into ``(payload, topic, extra_props)``.

    An object with a ``"payload"`` key is a full message (payload unwrapped
    via :func:`decode_payload`, remaining keys are extras); anything else is
    a bare payload.

    Raises:
        NdjsonError: on undecodable JSON or a malformed marker object.
    """
    try:
        obj = json.loads(line.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as e:
        raise NdjsonError(f"line is not valid JSON: {e}") from e

    if isinstance(obj, dict) and 'payload' in obj:
        payload = decode_payload(obj['payload'])
        topic = obj.get('topic', '') or ''
        extra = {k: v for k, v in obj.items() if k not in ('payload', 'topic')}
        return payload, topic, extra
    return decode_payload(obj), '', {}
