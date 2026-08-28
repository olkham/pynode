// Draw-on-frame geometry editor for 'geometry' properties (SV Line Counter /
// SV Polygon Zone). Opens a modal showing the node's last input frame
// (GET /api/nodes/<id>/frame, served by the deployed node) and lets the user
// place the geometry by clicking:
//   line:    click start, click end (2 points)
//   polygon: click each corner, then "Save" (>= 3 points); right-click undoes
// Saving hands the value back through the caller's `onSave` (which persists it
// to the working config, so it survives redeploys) AND POSTs the node's
// set_geometry action so a deployed node applies it live, mirroring the
// ControlSliderNode pattern.
//
// A shared service, not a node's own UI: the modal is generic frame-drawing
// machinery. The `geometry` property editor that opens it lives with the node
// that declares it, in pynode/nodes/Supervision/ui/.

import { API_BASE } from '../../config.js';

let overlay = null;         // lazily created modal root
let ctx = null;             // 2d context of the canvas
let session = null;         // { nodeId, propName, geometryType, points, img, scale, w, h }

const CANVAS_MAX_W = 800;
const CANVAS_MAX_H = 560;
const FALLBACK_W = 640;     // used when the node has no frame yet
const FALLBACK_H = 480;

function buildOverlay() {
    overlay = document.createElement('div');
    overlay.className = 'geometry-editor-modal';
    overlay.style.display = 'none';
    overlay.innerHTML = `
        <div class="geometry-editor-content">
            <div class="geometry-editor-header">
                <h3 id="geometry-editor-title">Draw geometry</h3>
                <button class="geometry-editor-close" type="button" title="Cancel">&times;</button>
            </div>
            <div class="geometry-editor-hint" id="geometry-editor-hint"></div>
            <canvas id="geometry-editor-canvas" class="geometry-editor-canvas"></canvas>
            <div class="geometry-editor-footer">
                <span class="geometry-editor-status" id="geometry-editor-status"></span>
                <div class="geometry-editor-actions">
                    <button class="btn btn-secondary" id="geometry-editor-clear" type="button">Clear</button>
                    <button class="btn btn-primary" id="geometry-editor-save" type="button" disabled>Save</button>
                </div>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    const canvas = overlay.querySelector('#geometry-editor-canvas');
    ctx = canvas.getContext('2d');

    overlay.querySelector('.geometry-editor-close').addEventListener('click', close);
    overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });
    overlay.querySelector('#geometry-editor-clear').addEventListener('click', () => {
        if (!session) return;
        session.points = [];
        redraw();
    });
    overlay.querySelector('#geometry-editor-save').addEventListener('click', save);
    canvas.addEventListener('click', onCanvasClick);
    canvas.addEventListener('contextmenu', (e) => {
        // right-click: undo last point
        e.preventDefault();
        if (session && session.points.length) {
            session.points.pop();
            redraw();
        }
    });
}

function toImageCoords(e) {
    const canvas = ctx.canvas;
    const rect = canvas.getBoundingClientRect();
    // canvas CSS size may differ from its pixel size; map through both scales
    const x = (e.clientX - rect.left) * (canvas.width / rect.width) / session.scale;
    const y = (e.clientY - rect.top) * (canvas.height / rect.height) / session.scale;
    return [Math.max(0, Math.min(session.w, Math.round(x))),
            Math.max(0, Math.min(session.h, Math.round(y)))];
}

function onCanvasClick(e) {
    if (!session) return;
    const maxPoints = session.geometryType === 'line' ? 2 : Infinity;
    if (session.points.length >= maxPoints) session.points = [];
    session.points.push(toImageCoords(e));
    redraw();
}

function redraw() {
    if (!session) return;
    const canvas = ctx.canvas;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (session.img) {
        ctx.drawImage(session.img, 0, 0, canvas.width, canvas.height);
    } else {
        ctx.fillStyle = '#1e1e22';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#888';
        ctx.font = '13px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No frame yet - deploy the flow to capture one. Clicks still work.',
            canvas.width / 2, canvas.height / 2);
    }

    const pts = session.points.map(([x, y]) => [x * session.scale, y * session.scale]);
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#00e5ff';
    ctx.fillStyle = 'rgba(0, 229, 255, 0.15)';

    if (pts.length) {
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
        if (session.geometryType === 'polygon' && pts.length >= 3) {
            ctx.closePath();
            ctx.fill();
        }
        ctx.stroke();
    }
    for (const [x, y] of pts) {
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#00e5ff';
        ctx.fill();
    }

    const need = session.geometryType === 'line' ? 2 : 3;
    const ok = session.points.length >= need;
    overlay.querySelector('#geometry-editor-save').disabled = !ok;
    overlay.querySelector('#geometry-editor-status').textContent =
        session.geometryType === 'line'
            ? `${session.points.length}/2 points`
            : `${session.points.length} points${ok ? '' : ' (need at least 3)'}`;
}

function serialize() {
    if (session.geometryType === 'line') {
        const [[x1, y1], [x2, y2]] = session.points;
        return `${x1},${y1},${x2},${y2}`;
    }
    return JSON.stringify(session.points);
}

async function save() {
    if (!session) return;
    const value = serialize();
    const { nodeId, onSave } = session;

    // Persist into the working config (survives reload / redeploy) ...
    onSave(value);

    // ... and push live to the deployed node, if there is one.
    try {
        await fetch(`${API_BASE}/nodes/${nodeId}/set_geometry`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value }),
        });
    } catch (err) {
        // Not deployed yet is fine - config carries the value to next deploy.
        console.debug('set_geometry live update skipped:', err);
    }
    close();
}

function close() {
    if (overlay) overlay.style.display = 'none';
    session = null;
}

async function fetchFrame(nodeId) {
    try {
        const resp = await fetch(`${API_BASE}/nodes/${nodeId}/editor_frame`);
        if (!resp.ok) return null;
        const body = await resp.json();
        if (!body || !body.data) return null;
        const img = new Image();
        await new Promise((resolve, reject) => {
            img.onload = resolve;
            img.onerror = reject;
            img.src = `data:image/jpeg;base64,${body.data}`;
        });
        return { img, w: body.width || img.naturalWidth, h: body.height || img.naturalHeight };
    } catch (err) {
        return null;
    }
}

function parseExisting(raw, geometryType) {
    if (!raw || typeof raw !== 'string') return [];
    try {
        if (geometryType === 'line' && !raw.trim().startsWith('[')) {
            const flat = raw.split(',').map(Number);
            if (flat.length === 4 && flat.every(Number.isFinite)) {
                return [[flat[0], flat[1]], [flat[2], flat[3]]];
            }
            return [];
        }
        const pts = JSON.parse(raw);
        if (Array.isArray(pts) && pts.every(p => Array.isArray(p) && p.length === 2)) {
            return pts.map(([x, y]) => [Math.round(x), Math.round(y)]);
        }
    } catch (err) { /* unparseable existing value - start empty */ }
    return [];
}

/**
 * Open the draw-on-frame modal.
 *
 * @param {object} args
 * @param {string} args.nodeId - node whose frame is drawn on
 * @param {string} args.geometryType - 'line' or 'polygon'
 * @param {string} args.value - the geometry already stored, if any
 * @param {(value: string) => void} args.onSave - receives the serialized geometry
 */
export async function openGeometryEditor({ nodeId, geometryType, value: raw, onSave }) {
    if (!overlay) buildOverlay();

    const frame = await fetchFrame(nodeId);
    const w = frame ? frame.w : FALLBACK_W;
    const h = frame ? frame.h : FALLBACK_H;
    const scale = Math.min(CANVAS_MAX_W / w, CANVAS_MAX_H / h, 1);

    session = {
        nodeId, geometryType, onSave,
        points: parseExisting(raw, geometryType),
        img: frame ? frame.img : null,
        scale, w, h,
    };

    ctx.canvas.width = Math.round(w * scale);
    ctx.canvas.height = Math.round(h * scale);

    overlay.querySelector('#geometry-editor-title').textContent =
        geometryType === 'line' ? 'Draw counting line' : 'Draw zone polygon';
    overlay.querySelector('#geometry-editor-hint').textContent =
        geometryType === 'line'
            ? 'Click the start point, then the end point. A third click starts over.'
            : 'Click each corner of the zone. Right-click to undo a point. Save when done.';

    overlay.style.display = 'flex';
    redraw();
}
