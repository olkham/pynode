# Interop example: talking to the UDP / TCP nodes from Node-RED

The `SocketNode` nodes (`UdpOutNode`/`UdpInNode` = **UDP Out**/**UDP In**,
`TcpOutNode`/`TcpInNode` = **TCP Out**/**TCP In**) are generic - anything
that speaks their wire format can interoperate. This folder is **one worked
example**: a Node-RED flow that talks to them, plus a standalone diagnostic.
Nothing here is required to use the nodes PyNode-to-PyNode.

- **UDP** uses the `PNB1` wire protocol, defined once in
  `pynode/nodes/SocketNode/udp_protocol.py` (Python) and mirrored by hand in
  the two Node-RED function nodes below (JavaScript). See that module's
  docstring for the full byte-layout spec.
- **TCP** uses newline-delimited JSON (`pynode/nodes/SocketNode/ndjson_protocol.py`)
  and needs no custom decode code at all.

## Files

- `nodered-example-flow.json` - an importable Node-RED flow with two tabs:
  - **"PyNode Bridge (PNB1)"** - the UDP transport, both directions, using
    only core nodes (`udp in`, `udp out`, `function`, `debug`, `inject`):
    - **PyNode -> Node-RED**: `udp in` -> function `PNB1 reassemble` -> `debug`
    - **Node-RED -> PyNode**: `inject` -> function `PNB1 chunk+send` -> `udp out`
  - **"PyNode Bridge (TCP/NDJSON)"** - the TCP transport (see below).
- `../udp_probe.py` - standalone, stdlib-only UDP diagnostic (copy the single
  file anywhere): `listen` mode prints/decodes arriving PNB1 datagrams,
  `send` mode injects a test message. See Troubleshooting below.
- `README.md` - this file.

## Importing the flow

1. Open the Node-RED editor.
2. Menu (top-right hamburger) -> **Import** -> **select a file to import** ->
   choose `nodered-example-flow.json`.
3. Choose "new flow" (each tab imports into its own tab) and click **Import**.
4. Double-click the `udp in`, `udp out`, `tcp in`, `tcp out`, and `inject`
   nodes and adjust the host/port fields (see below), then **Deploy**.

Node-RED's UDP/TCP node field names are stable across recent versions, but if
your version's editor shows different fields, use the editor's own labels as
the source of truth - re-enter host/port there rather than hand-editing the
JSON.

## UDP direction 1: PyNode -> Node-RED

```
PyNode: [UDP Out node]  --UDP-->  Node-RED: [udp in] -> [PNB1 reassemble] -> ...
```

- In PyNode, add a **UDP Out** node downstream of whatever you want to
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
  - With the UDP Out node's **Include Extra Message Properties** checkbox on,
    EVERY property of the PyNode message except `payload`/`topic` (underscore
    ones included: `_msgid`, `_timestamp_orig`, `_timestamp_emit`, `_age`,
    `_queue_length`, `drop_count`, plus custom fields) is forwarded and
    merged onto the top level of the emitted message - the Node-RED msg
    replicates the PyNode msg exactly. Values that aren't JSON-serializable
    are skipped individually.
- An incomplete message (a chunk was lost) is silently dropped after 2000ms
  (`DEFAULT_REASSEMBLY_TIMEOUT_MS` in the function code) - nothing is emitted
  for it. There is no retransmission (UDP is fire-and-forget both ways).

## UDP direction 2: Node-RED -> PyNode

```
Node-RED: [inject] -> [PNB1 chunk+send] -> [udp out]  --UDP-->  PyNode: [UDP In node]
```

- In PyNode, add a **UDP In** node. Set **Bind Host** (default `0.0.0.0`, or
  `127.0.0.1` to only accept from the same machine) and **Port** to match the
  `udp out` node's target port (default in this flow: `7402`).
- In Node-RED, the `udp out` node's **Host**/**Address** field must point at
  the machine running PyNode, and its **Port** must match the UDP In node's
  **Port**.
- Replace the sample `inject` node with whatever actually produces the
  message you want to send. Anything upstream of `PNB1 chunk+send` works as
  long as it sets `msg.payload` (and optionally `msg.topic`).
- `PNB1 chunk+send` returns an **array of messages** (one per UDP datagram)
  on its single output - wire it straight into **one** `udp out` node so
  each array element becomes exactly one UDP packet, in order.
- `msg.payload` types handled by `classifyPayload()` in the function:
  - A `Buffer` starting with the JPEG SOI marker (`0xFF 0xD8`) is tagged
    `payload_type: "jpeg"` so it decodes into a real image (`cv2.imdecode`)
    on the PyNode side.
  - Any other `Buffer` is tagged `payload_type: "bytes"` (forwarded as raw
    Python `bytes`).
  - Anything else (object, array, string, number, boolean, `null`) is
    JSON-encoded, tagged `payload_type: "json"`.

## TCP/NDJSON transport (simpler alternative)

The flow file's second tab, **"PyNode Bridge (TCP/NDJSON)"**, pairs with the
**TCP Out** / **TCP In** PyNode nodes. One message = one JSON line over a
persistent TCP connection - reliable, ordered, no size limit, no
chunking/reassembly/fragmentation, and the receive path uses only core nodes:

```
PyNode: [TCP Out] --connects to--> Node-RED: [tcp in :7403, stream of strings
        split on \n] -> [json] -> [promote to msg (optional)] -> ...

Node-RED: [anything] -> [NDJSON stringify function] -> [tcp out, connect to
          <pynode-host>:7404] --> PyNode: [TCP In :7404]
```

- The `promote to msg` function is one `return msg.payload;`-style line that
  lifts the bridged object to the top level so the Node-RED msg replicates
  the PyNode msg exactly; delete it if you prefer the object in
  `msg.payload`.
- The `NDJSON stringify` function is the only code the send direction needs:
  `msg.payload = JSON.stringify({payload: msg.payload, topic: msg.topic ||
  ''}) + "\n";`. A bare JSON value followed by `\n` also works - PyNode
  treats a non-object line as the payload itself.
- Binary payloads (images) travel base64-wrapped in the JSON
  (`{"_pnb": "jpeg", "data": "<base64>"}`, decode in Node-RED with
  `Buffer.from(msg.payload.data, 'base64')`), costing ~33% extra size - for
  sustained high-rate video frames prefer the UDP (PNB1) tab.
- TCP backpressure: a slow/stalled consumer makes PyNode's sends time out
  and drop (counted on the node) rather than queue unboundedly.

**When to use which:** TCP/NDJSON for control messages, events, detections,
telemetry (simpler, reliable). UDP/PNB1 for live video and very high message
rates (drop-friendly, binary-native).

## Chunk size

The UDP Out node's **Chunk Size** select (60000 bytes, or 1400 for MTU-safe
WAN links) only controls how a large payload is *fragmented* - decoding does
not depend on it, so the two ends do not strictly need to agree. To match on
the Node-RED side, edit the `const CHUNK_SIZE = DEFAULT_CHUNK_SIZE;` line in
`PNB1 chunk+send` (e.g. to `MTU_CHUNK_SIZE`) so packet counts stay sane on
constrained links.

## Ports

This flow and the bundled PyNode example (menu -> Examples -> "16 · UDP/TCP
Bridge", file `pynode/static/examples/16-socket-bridge.json`) use **7401**
(PyNode -> Node-RED UDP) and **7402** (Node-RED -> PyNode UDP), plus **7403**
/ **7404** for TCP, as placeholders. They're arbitrary - pick any free ports,
just keep both ends of each direction consistent.

## Troubleshooting: Node-RED receives nothing (UDP)

> **Seeing `PNB1` plus gibberish/JSON in the debug panel?** Datagrams ARE
> arriving - you are looking at the raw wire bytes (16-byte binary header +
> metadata + payload). Two fixes: set the `udp in` node's **Output** to
> `a Buffer` (not `a string` - that corrupts the binary header), and wire it
> through the **PNB1 reassemble** function node from this flow rather than
> straight into debug. The reassemble node emits the decoded message.

Work through these in order - each step isolates one link of the chain.

1. **The UDP Out node's Host defaults to `127.0.0.1`.** If Node-RED runs on a
   different machine, packets never leave the PyNode box until you set
   **Host** to the Node-RED machine's IP. This is the most common cause.
2. **Prove datagrams reach the Node-RED machine.** Copy `../udp_probe.py`
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
   frames don't, set the UDP Out node's **Chunk Size** to `1400`.
5. **Docker/firewall notes.** `--network host` needs no port mapping
   (with the default bridge network you'd need `-p 7401:7401/udp` instead
   - TCP-only `-p 7401:7401` does NOT cover UDP). `ufw allow 7401/udp`
   covers inbound to the host. The `PORT`/`1881` setting only moves the
   editor UI, not the flow's UDP ports.

## Caveats (read before relying on this in production)

- **UDP is unreliable.** Datagrams can be lost, duplicated, or reordered by
  the network. Neither side retransmits or acknowledges. A message missing
  even one chunk is dropped after the reassembly timeout. Use the UDP nodes
  for loopback/LAN telemetry/video where an occasional dropped message is
  acceptable, or the TCP nodes when you need guaranteed delivery.
- **No encryption or authentication.** Anyone who can reach the configured
  port can send to it or sniff traffic on it. Do not expose these ports
  directly to an untrusted network; tunnel over VPN/SSH if you must.
- **This flow has not been executed against a live Node-RED instance** as
  part of building it - it was written to match Node-RED's documented core
  node schemas and hand-verified for constant parity against
  `udp_protocol.py` (see
  `tests/test_socket_nodes.py::test_flow_json_constants_match_python`).
  Verify the node field names against your Node-RED version's editor after
  import, before depending on this in production.
