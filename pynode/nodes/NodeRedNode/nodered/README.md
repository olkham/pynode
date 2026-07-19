# PyNode <-> Node-RED UDP Bridge (PNB1) - Node-RED side

This folder contains the **Node-RED half** of the PyNode <-> Node-RED bridge.
The PyNode half is `NodeRedOutNode` ("Node-RED Out") and `NodeRedInNode`
("Node-RED In") in `pynode/nodes/NodeRedNode/`. Both sides speak the same
`PNB1` wire protocol, defined once in `pynode/nodes/NodeRedNode/bridge_protocol.py`
(Python) and mirrored by hand in the two function nodes below (JavaScript).
See that module's docstring for the full byte-layout spec.

## Files

- `pynode-bridge-flow.json` - an importable Node-RED flow (one tab) that
  implements **both directions** using only core Node-RED nodes (`udp in`,
  `udp out`, `function`, `debug`, `inject`, `comment`):
  - **PyNode -> Node-RED**: `udp in` -> function `PNB1 reassemble` -> `debug`
  - **Node-RED -> PyNode**: `inject` -> function `PNB1 chunk+send` -> `udp out`
- `udp_probe.py` - standalone, stdlib-only diagnostic (copy the single file
  anywhere): `listen` mode prints/decodes arriving PNB1 datagrams, `send`
  mode injects a test message. See Troubleshooting below.
- `README.md` - this file.

## Importing the flow

1. Open the Node-RED editor.
2. Menu (top-right hamburger) -> **Import** -> **select a file to import** ->
   choose `pynode-bridge-flow.json`.
3. Choose "new flow" (it imports into its own tab, "PyNode Bridge (PNB1)") and
   click **Import**.
4. Double-click the `udp in`, `udp out`, and `inject` nodes and adjust the
   host/port fields (see below), then **Deploy**.

Node-RED's UDP node field names are stable across recent versions, but if
your version's editor shows different fields for `udp in`/`udp out`, use the
editor's own labels as the source of truth - re-enter host/port there rather
than hand-editing the JSON.

## Direction 1: PyNode -> Node-RED

```
PyNode: [Node-RED Out node]  --UDP-->  Node-RED: [udp in] -> [PNB1 reassemble] -> ...
```

- In PyNode, add a **Node-RED Out** node downstream of whatever you want to
  forward. Set its **Host** to the machine running Node-RED, and **Port** to
  match the `udp in` node's **Local UDP Port** (default in this flow: `7401`).
- In Node-RED, the `udp in` node **must** have **Output** set to `buffer`
  (raw bytes) - the reassemble function parses the PNB1 header directly from
  `msg.payload`, so a `string`/`base64` datatype would corrupt it.
- The `PNB1 reassemble` function emits one message per fully-reassembled
  PyNode message:
  - `msg.payload`: a parsed JS object/array (JSON), a `Buffer` (raw bytes or
    JPEG - feed straight into an image-preview node), or a `Buffer` of raw
    array bytes (`raw_numpy` - see `msg._pnb1.dtype`/`msg._pnb1.shape`, there
    is no numpy in Node-RED so this is passed through unparsed).
  - `msg.topic`: the topic PyNode's message had (empty string if none).
  - `msg._pnb1`: `{messageId, payloadType, totalSize[, dtype, shape]}` for
    debugging/introspection.
  - Any "extra" message properties PyNode's Node-RED Out node was configured
    to forward (its **Include Extra Message Properties** checkbox) are
    merged onto the top level of the emitted message.
- An incomplete message (a chunk was lost) is silently dropped after 2000ms
  (`DEFAULT_REASSEMBLY_TIMEOUT_MS` in the function code) - nothing is emitted
  for it. There is no retransmission (UDP is fire-and-forget both ways).

## Direction 2: Node-RED -> PyNode

```
Node-RED: [inject] -> [PNB1 chunk+send] -> [udp out]  --UDP-->  PyNode: [Node-RED In node]
```

- In PyNode, add a **Node-RED In** node. Set **Bind Host** (default
  `0.0.0.0`, or `127.0.0.1` to only accept from the same machine) and
  **Port** to match the `udp out` node's target port (default in this flow:
  `7402`).
- In Node-RED, the `udp out` node's **Host**/**Address** field must point at
  the machine running PyNode, and its **Port** must match the Node-RED In
  node's **Port**.
- Replace the sample `inject` node with whatever actually produces the
  message you want to send (an MQTT-in, a camera/image node, another
  function, ...). Anything upstream of `PNB1 chunk+send` works as long as it
  sets `msg.payload` (and optionally `msg.topic`).
- `PNB1 chunk+send` returns an **array of messages** (one per UDP datagram)
  on its single output - wire it straight into **one** `udp out` node so
  each array element becomes exactly one UDP packet, in order. Do not put
  anything else between them (a rate limiter/delay node would still work
  functionally, but there is no reason to - one function call already
  produces the complete, ordered chunk sequence for one message).
- `msg.payload` types handled by `classifyPayload()` in the function:
  - A `Buffer` starting with the JPEG SOI marker (`0xFF 0xD8`) is tagged
    `payload_type: "jpeg"` so it decodes into a real image (`cv2.imdecode`)
    on the PyNode side.
  - Any other `Buffer` is tagged `payload_type: "bytes"` (forwarded as raw
    Python `bytes`).
  - Anything else (object, array, string, number, boolean, `null`) is
    JSON-encoded, tagged `payload_type: "json"`.

## Chunk size

The Python side's **Chunk Size** select (60000 bytes, or 1400 for MTU-safe
WAN links) only controls how a large payload is *fragmented* - decoding does
not depend on it, so the two ends do not strictly need to agree. In practice,
keep the JS `CHUNK_SIZE` constant in `PNB1 chunk+send` reasonably close to
what you'd pick for `NodeRedOutNode` (edit the `const CHUNK_SIZE =
DEFAULT_CHUNK_SIZE;` line, e.g. to `MTU_CHUNK_SIZE`, for the same WAN-safety
reasoning) so packet counts stay sane on constrained links.

## Ports

This flow and the bundled PyNode example (menu -> Examples -> "16 · Node-RED
Bridge", file `pynode/static/examples/16-nodered-bridge.json`) both use
**7401** (PyNode -> Node-RED) and **7402** (Node-RED -> PyNode) as
placeholders. They're arbitrary - pick any free UDP ports, just keep both
ends of each direction consistent.

## Troubleshooting: Node-RED receives nothing

Work through these in order - each step isolates one link of the chain.

1. **PyNode's "Node-RED Out" Host defaults to `127.0.0.1`.** If Node-RED
   runs on a different machine, packets never leave the PyNode box until you
   set **Host** to the Node-RED machine's IP. This is the most common cause.
2. **Prove datagrams reach the Node-RED machine.** Copy `udp_probe.py`
   there, temporarily stop the Node-RED flow (or use a spare port on both
   ends), and run:

       python3 udp_probe.py listen 7401

   Trigger a send from PyNode. If nothing prints, it's network-level:
   wrong Host (step 1), a firewall, or fragment loss (step 4). If datagrams
   print here but Node-RED's debug node stays silent, it's the flow/Node-RED
   side (step 3).
3. **Prove the flow works, with no network involved.** On the Node-RED
   machine (flow deployed, `udp in` bound to 7401):

       python3 udp_probe.py send 127.0.0.1 7401 "hello from probe"

   The `PNB1 in debug` node should print the message. If not: check the
   `udp in` node's **Output** is `a Buffer` (a string output corrupts the
   binary header), the port matches, and the Node-RED log for "port already
   in use" (another flow or process may own 7401).
4. **Large payloads only (video frames): IP fragmentation.** The default
   60000-byte chunk becomes ~40 IP fragments per datagram on a typical
   1500-MTU network; some routers/firewalls drop fragments, and losing ONE
   fragment discards the whole datagram. If small Inject messages arrive but
   frames don't, set the PyNode node's **Chunk Size** to `1400`.
5. **Docker/firewall notes.** `--network host` needs no port mapping
   (with the default bridge network you'd need `-p 7401:7401/udp` instead
   - TCP-only `-p 7401:7401` does NOT cover UDP). `ufw allow 7401/udp`
   covers inbound to the host. The `PORT`/`1881` setting only moves the
   editor UI, not the flow's UDP ports.

## Caveats (read before relying on this in production)

- **UDP is unreliable.** Datagrams can be lost, duplicated, or reordered by
  the network. Neither side retransmits or acknowledges. A message missing
  even one chunk is dropped after the reassembly timeout. This bridge is
  designed for loopback/LAN use (telemetry, video preview, control
  messages) where an occasional dropped message is acceptable - not for
  anything requiring guaranteed delivery.
- **No encryption or authentication.** Anyone who can reach the configured
  UDP port can send to it or sniff traffic on it. Do not expose these ports
  directly to an untrusted network (the public internet, an untrusted
  Wi-Fi/VLAN); tunnel over VPN/SSH if you need to bridge across one.
- **This flow has not been executed against a live Node-RED instance** as
  part of building it (no Node-RED runtime is available in the environment
  that produced it) - it was written to match Node-RED's documented core
  `udp in`/`udp out`/`function` node schemas and hand-verified for constant
  parity against `bridge_protocol.py` (see
  `tests/test_nodered_bridge.py::test_flow_json_constants_match_python`).
  Verify the `udp in`/`udp out` field names against your Node-RED version's
  editor after import, before depending on this in production.
