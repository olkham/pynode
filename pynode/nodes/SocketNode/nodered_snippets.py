"""Importable Node-RED flow snippets for the socket nodes' Info panels.

Each socket node's Info panel offers a ready-made Node-RED flow the user can
copy and paste straight into Node-RED's Import dialog (menu -> Import ->
paste -> Import), so the "how do I decode this on the Node-RED side?"
question is answered in the editor instead of in a README nobody opens.

The snippets are not hand-written here: they are *sliced out of* the worked
example flow in ``interop/nodered-example-flow.json``, whose embedded
JavaScript is already checked for wire-format parity against
``udp_protocol.py`` by ``tests/test_socket_nodes.py``. One source of truth -
the JS a user copies from the Info panel can never drift from the JS in the
example flow, and neither can drift from the Python.

Each snippet is a JSON array of Node-RED nodes:

* a generated ``comment`` node stating what to change after importing,
* the transport node (``udp in``/``udp out``/``tcp in``/``tcp out``),
* whatever decoding/encoding nodes that direction needs.

The ``port`` argument rewrites the transport node's port so the copied flow
matches the PyNode node's own default rather than the example flow's
(arbitrary) port pairing.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

_FLOW_PATH = Path(__file__).resolve().parent / 'interop' / 'nodered-example-flow.json'

# The Node-RED node types whose 'port' field is rewritten to match the PyNode
# node the snippet is shown on. Every snippet contains exactly one of these.
_TRANSPORT_TYPES = ('udp in', 'udp out', 'tcp in', 'tcp out')

# Where the pasted flow is laid out (Node-RED preserves relative positions;
# these just keep the snippet clear of the tab's top-left corner).
_ORIGIN_X = 180
_ORIGIN_Y = 120

# kind -> (example-flow node ids in wire order, comment title, comment body).
# The body is .format()ed with the port, so it can never quote a stale one.
_SNIPPETS: Dict[str, Tuple[Tuple[str, ...], str, str]] = {
    'udp_out': (
        ('pnb1000000000003',   # udp in
         'pnb1000000000004',   # function: PNB1 reassemble
         'pnb1000000000005'),  # debug
        "Receive from a PyNode 'UDP Out' node (PNB1)",
        "PyNode's 'UDP Out' node sends PNB1 datagrams here. Set its Host to "
        "this machine and its Port to {port} to match the 'udp in' node. "
        "Leave the 'udp in' node's Output set to 'a Buffer' - a string "
        "output corrupts the binary PNB1 header. The 'PNB1 reassemble' "
        "function joins the chunks back into one message per PyNode message.",
    ),
    'udp_in': (
        ('pnb1000000000007',   # inject
         'pnb1000000000008',   # function: PNB1 chunk+send
         'pnb1000000000009'),  # udp out
        "Send to a PyNode 'UDP In' node (PNB1)",
        "Set the 'udp out' node's Address to the machine running PyNode (it "
        "defaults to 127.0.0.1) and its Port to {port} to match the PyNode "
        "'UDP In' node. Replace the inject node with whatever produces your "
        "message. 'PNB1 chunk+send' returns an array of messages (one per "
        "datagram) - keep it wired to exactly one 'udp out' node.",
    ),
    'tcp_out': (
        ('pnbtcp0000tcpin1',   # tcp in
         'pnbtcp0000json01',   # json
         'pnbtcp00promote1',   # function: promote to msg (optional)
         'pnbtcp000debug01'),  # debug
        "Receive from a PyNode 'TCP Out' node (NDJSON)",
        "PyNode's 'TCP Out' node connects here. Set its Host to this machine "
        "and its Port to {port} to match the 'tcp in' node. The 'tcp in' "
        "node must stay in 'stream of Strings' mode delimited by \\n - in "
        "'stream of Buffers' mode you get raw bytes split on TCP read "
        "boundaries rather than one message per line.",
    ),
    'tcp_in': (
        ('pnbtcp00inject01',   # inject
         'pnbtcp00string01',   # function: NDJSON stringify
         'pnbtcp000tcpout1'),  # tcp out
        "Send to a PyNode 'TCP In' node (NDJSON)",
        "Set the 'tcp out' node's Host to the machine running PyNode (it "
        "defaults to 127.0.0.1) and its Port to {port} to match the PyNode "
        "'TCP In' node. Replace the inject node with whatever produces your "
        "message. 'NDJSON stringify' adds the one thing the wire format "
        "needs: one JSON object per line, terminated by \\n.",
    ),
}


def _load_flow() -> List[Dict[str, Any]]:
    return json.loads(_FLOW_PATH.read_text(encoding='utf-8'))


@lru_cache(maxsize=None)
def flow_snippet(kind: str, port: int) -> str:
    """Return an importable Node-RED flow (JSON array text) for ``kind``.

    Args:
        kind: one of ``udp_out``, ``udp_in``, ``tcp_out``, ``tcp_in`` - named
            for the PyNode node the snippet pairs with, not for the Node-RED
            node inside it (the ``udp_out`` snippet *receives*).
        port: written onto the snippet's transport node, so the copied flow
            matches the PyNode node's configured/default port.

    Raises:
        KeyError: on an unknown ``kind`` (a coding error, caught by tests).
    """
    ids, title, guidance = _SNIPPETS[kind]

    try:
        by_id = {n['id']: n for n in _load_flow()}
        nodes = [dict(by_id[node_id]) for node_id in ids]
    except (OSError, ValueError, KeyError) as e:
        # Never let a missing or hand-edited example file break node import -
        # the node itself is unaffected, so degrade to a pointer at the source.
        return (f"Could not read the bundled example flow ({_FLOW_PATH.name}: "
                f"{e}). See pynode/nodes/SocketNode/interop/ in the PyNode "
                f"source for the full flow and its README.")

    min_x = min(n.get('x', 0) for n in nodes)
    min_y = min(n.get('y', 0) for n in nodes)
    for node in nodes:
        # Drop the tab reference: without a 'z' Node-RED imports onto the
        # currently open flow instead of dangling off a tab that isn't there.
        node.pop('z', None)
        node['x'] = node.get('x', 0) - min_x + _ORIGIN_X
        node['y'] = node.get('y', 0) - min_y + _ORIGIN_Y
        if node.get('type') in _TRANSPORT_TYPES:
            node['port'] = str(port)  # Node-RED stores ports as strings

    comment = {
        'id': f"pynodehelp{kind.replace('_', '')}",
        'type': 'comment',
        'name': title,
        'info': guidance.format(port=port),
        'x': _ORIGIN_X,
        'y': _ORIGIN_Y - 60,
        'wires': [],
    }
    return json.dumps([comment] + nodes, indent=2)


HOW_TO_IMPORT = ("Copy this, then in Node-RED: menu (top right) -> Import -> "
                 "paste into the box -> Import.")
