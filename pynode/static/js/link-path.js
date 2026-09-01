// Connection path geometry.
//
// A port of Node-RED's `generateLinkPath` (editor-client/src/js/ui/view.js),
// adapted to this editor's node metrics. Ports here are always output-right ->
// input-left, so Node-RED's `sc` side parameter is fixed at 1 and folded out.
//
// The shape depends on where the target sits relative to the source:
//
//   forward (target to the right)   one cubic, flattening towards a straight
//                                   line as the ports get close
//
//   backward, level                 a squared detour below both nodes: down,
//                                   straight across, back up
//
//   backward, offset (the common    a shallow shoulder out of the output, a
//   case - nodes stacked            smooth sweep through the midpoint, and a
//   vertically)                     shoulder back into the input
//
// The two backward forms keep their turns shallow - never more than half a node
// tall - and let the sweep through the middle carry the vertical distance. That
// is what stops a tall backward link from turning into two semicircles joined
// by a straight vertical line.

// Curve units. Node-RED works in its own fixed node size (100x30); NODE_W is
// simply the unit all the curve reaches are expressed in, and NODE_H tracks
// `.node`'s min-height in style.css, which is where the ports sit.
const NODE_W = 130;
const NODE_H = 30;

// Control-point reach for a forward link, in units of NODE_W.
const FORWARD_SCALE = 0.75;

// Backward links reach out this far horizontally, in units of NODE_W. The reach
// is dynamic: ports close together in either axis get a tighter turn than ones
// far apart, so short hops stay compact without flattening long links.
const BACK_SCALE_MAX = 0.4;
const BACK_SCALE_MIN = 0.2;

// Ports closer to level than this have no room for a sweep between them, so the
// link detours below the nodes instead, dropping LEVEL_DROP past the lower port.
const LEVEL_DY = 10;
const LEVEL_DROP = 25;

/**
 * SVG path data for a link from an output port to an input port.
 *
 * Both ports face right: the line leaves `(x1, y1)` heading right and enters
 * `(x2, y2)` heading right.
 *
 * @param {number} x1 source (output port) x, canvas coordinates
 * @param {number} y1 source (output port) y
 * @param {number} x2 target (input port) x
 * @param {number} y2 target (input port) y
 * @returns {string} value for a <path> `d` attribute
 */
export function linkPath(x1, y1, x2, y2) {
    const dx = x2 - x1;
    const dy = y2 - y1;
    const delta = Math.sqrt(dx * dx + dy * dy);

    if (dx > 0) {
        // Forward: one cubic. The control points pull in once the ports are
        // closer together than a node width, otherwise short links bulge into
        // an S instead of running straight across.
        const c = NODE_W * FORWARD_SCALE * Math.min(1, delta / NODE_W);
        return `M ${x1} ${y1} C ${x1 + c} ${y1}, ${x2 - c} ${y2}, ${x2} ${y2}`;
    }

    const scale = BACK_SCALE_MAX - (BACK_SCALE_MAX - BACK_SCALE_MIN) *
        Math.max(0, (NODE_W - Math.min(Math.abs(dx), Math.abs(dy))) / NODE_W);

    if (Math.abs(dy) < LEVEL_DY) {
        // Level ports: drop below both nodes, run flat across, come back up.
        // The corners are fixed-radius so the flat middle stays flat however
        // far apart the nodes are.
        const bottomY = Math.max(y1, y2) + LEVEL_DROP;
        const downH = bottomY - y1;
        const upH = bottomY - y2;
        return `M ${x1} ${y1}` +
            ` C ${x1 + 15} ${y1}, ${x1 + 25} ${y1 + 5}, ${x1 + 25} ${y1 + downH / 2}` +
            ` C ${x1 + 25} ${bottomY - 5}, ${x1 + 15} ${bottomY}, ${x1} ${bottomY}` +
            ` h ${dx}` +
            ` C ${x2 - 15} ${bottomY}, ${x2 - 25} ${bottomY - 5}, ${x2 - 25} ${y2 + upH / 2}` +
            ` C ${x2 - 25} ${y2 + 5}, ${x2 - 15} ${y2}, ${x2} ${y2}`;
    }

    // Offset ports: shoulder out, sweep through the midpoint, shoulder in.
    // `top` and `bottom` are the anchors just outside each port; both stay
    // within half a node of their port, so the shoulders are shallow and the
    // sweep between them absorbs however much vertical distance there is.
    const cpH = NODE_H / 2;
    const down = dy > 0;
    const midX = Math.floor(x2 - dx / 2);
    const midY = Math.floor(y2 - dy / 2);
    const yq = (y2 + midY) / 2;

    const topX = x1 + NODE_W * scale;
    const topY = down ? Math.min(yq - dy / 2, y1 + cpH) : Math.max(yq - dy / 2, y1 - cpH);
    const bottomX = x2 - NODE_W * scale;
    const bottomY = down ? Math.max(yq, y2 - cpH) : Math.min(yq, y2 + cpH);
    const xq = (x1 + topX) / 2;
    const scy = down ? 1 : -1;

    // Control points for the four segments; each S reflects the previous one,
    // so the whole chain stays smooth.
    const cp = [
        [xq, y1],
        [topX, down ? Math.max(y1, topY - cpH) : Math.min(y1, topY + cpH)],
        [xq, down ? Math.min(midY, topY + cpH) : Math.max(midY, topY - cpH)],
        [bottomX, down ? Math.max(midY, bottomY - cpH) : Math.min(midY, bottomY + cpH)],
        [(x2 + bottomX) / 2, y2],
    ];
    // The mid anchor is more than a shoulder away from both ports: tuck the
    // control points in so the shoulders stay tight rather than bowing out.
    if (cp[2][1] === topY + scy * cpH) {
        if (Math.abs(dy) < cpH * 10) {
            cp[1][1] = topY - scy * cpH / 2;
            cp[3][1] = bottomY - scy * cpH / 2;
        }
        cp[2][0] = topX;
    }

    return `M ${x1} ${y1}` +
        ` C ${cp[0][0]} ${cp[0][1]}, ${cp[1][0]} ${cp[1][1]}, ${topX} ${topY}` +
        ` S ${cp[2][0]} ${cp[2][1]}, ${midX} ${midY}` +
        ` S ${cp[3][0]} ${cp[3][1]}, ${bottomX} ${bottomY}` +
        ` S ${cp[4][0]} ${cp[4][1]}, ${x2} ${y2}`;
}
