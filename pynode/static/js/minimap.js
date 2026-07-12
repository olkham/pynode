// Minimap: a toggleable lower-right overview panel of the canvas.
//
// Rendering tech: a single small 2D <canvas>. All node rectangles plus the
// FoV rectangle are one clearRect + a few fillRects per redraw - no DOM
// element management, which keeps redraws O(nodes) and allocation-free.
// Redraws are event-driven (refreshMinimap() hooks in node create/move/
// delete, tab switch, zoom and container scroll) and coalesced through
// requestAnimationFrame - there is no timer.
import { state } from './state.js';
import { getZoom, getCanvasContainer, onViewportChange } from './viewport.js';

const VISIBLE_STORAGE_KEY = 'pynode.minimap.visible';

// Nominal node size (matches .node { min-width: 120px; min-height: 30px })
// used when a node's DOM element is not available.
const NOMINAL_NODE_W = 120;
const NOMINAL_NODE_H = 30;
const WORLD_PADDING = 60;

let rafPending = false;

// world -> minimap mapping of the last draw (used by drag-to-pan)
let mapScale = 1;
let mapOffsetX = 0;
let mapOffsetY = 0;
let lastFovRect = null; // {x, y, w, h} in minimap pixels

function getPanel() {
    return document.getElementById('minimap-panel');
}

function getMapCanvas() {
    return document.getElementById('minimap-canvas');
}

function isVisible() {
    const panel = getPanel();
    return panel && !panel.classList.contains('hidden');
}

/**
 * Request a minimap redraw (coalesced via requestAnimationFrame).
 * Cheap to call from any node move/create/delete/tab-switch path.
 */
export function refreshMinimap() {
    if (!isVisible() || rafPending) return;
    rafPending = true;
    requestAnimationFrame(() => {
        rafPending = false;
        drawMinimap();
    });
}

function getNodeWorldRect(nodeId, nodeData) {
    const nodeEl = document.getElementById(`node-${nodeId}`);
    // offsetWidth/Height are layout (untransformed) px == canvas units
    const w = nodeEl ? nodeEl.offsetWidth : NOMINAL_NODE_W;
    const h = nodeEl ? nodeEl.offsetHeight : NOMINAL_NODE_H;
    return { x: nodeData.x, y: nodeData.y, w: w || NOMINAL_NODE_W, h: h || NOMINAL_NODE_H };
}

function drawMinimap() {
    const mapCanvas = getMapCanvas();
    const container = getCanvasContainer();
    if (!mapCanvas || !container) return;

    const ctx = mapCanvas.getContext('2d');
    const mw = mapCanvas.width;
    const mh = mapCanvas.height;
    const zoom = getZoom();

    // Visible region of the world (canvas coords)
    const view = {
        x: container.scrollLeft / zoom,
        y: container.scrollTop / zoom,
        w: container.clientWidth / zoom,
        h: container.clientHeight / zoom
    };

    // World bounds = union of all node rects and the current viewport
    let minX = view.x;
    let minY = view.y;
    let maxX = view.x + view.w;
    let maxY = view.y + view.h;

    const nodeRects = [];
    state.nodes.forEach((nodeData, nodeId) => {
        const r = getNodeWorldRect(nodeId, nodeData);
        nodeRects.push({ rect: r, color: nodeData.color });
        minX = Math.min(minX, r.x);
        minY = Math.min(minY, r.y);
        maxX = Math.max(maxX, r.x + r.w);
        maxY = Math.max(maxY, r.y + r.h);
    });

    minX -= WORLD_PADDING;
    minY -= WORLD_PADDING;
    maxX += WORLD_PADDING;
    maxY += WORLD_PADDING;

    const worldW = Math.max(1, maxX - minX);
    const worldH = Math.max(1, maxY - minY);
    mapScale = Math.min(mw / worldW, mh / worldH);
    mapOffsetX = (mw - worldW * mapScale) / 2 - minX * mapScale;
    mapOffsetY = (mh - worldH * mapScale) / 2 - minY * mapScale;

    const toMap = (x, y) => ({
        x: x * mapScale + mapOffsetX,
        y: y * mapScale + mapOffsetY
    });

    // Background
    ctx.clearRect(0, 0, mw, mh);
    ctx.fillStyle = '#1e1e1e';
    ctx.fillRect(0, 0, mw, mh);

    // Node rectangles (node's own color, neutral fallback)
    nodeRects.forEach(({ rect, color }) => {
        const p = toMap(rect.x, rect.y);
        ctx.fillStyle = color || '#5a5a5e';
        ctx.fillRect(p.x, p.y, Math.max(2, rect.w * mapScale), Math.max(2, rect.h * mapScale));
    });

    // FoV (visible viewport) rectangle
    const fovP = toMap(view.x, view.y);
    const fovW = view.w * mapScale;
    const fovH = view.h * mapScale;
    lastFovRect = { x: fovP.x, y: fovP.y, w: fovW, h: fovH };

    ctx.fillStyle = 'rgba(0, 152, 255, 0.12)';
    ctx.fillRect(fovP.x, fovP.y, fovW, fovH);
    ctx.strokeStyle = '#0098ff';
    ctx.lineWidth = 1;
    ctx.strokeRect(fovP.x + 0.5, fovP.y + 0.5, fovW - 1, fovH - 1);
}

function mapPointToWorld(mapX, mapY) {
    return {
        x: (mapX - mapOffsetX) / mapScale,
        y: (mapY - mapOffsetY) / mapScale
    };
}

/** Scroll the main canvas so the given world point is at the view center. */
function centerViewOnWorldPoint(worldX, worldY) {
    const container = getCanvasContainer();
    if (!container) return;
    const zoom = getZoom();
    container.scrollLeft = worldX * zoom - container.clientWidth / 2;
    container.scrollTop = worldY * zoom - container.clientHeight / 2;
    refreshMinimap();
}

function setupMinimapPanning(mapCanvas) {
    let dragging = false;
    // Offset (in world coords) between the pointer and the FoV center, so
    // grabbing the FoV rect drags it without jumping.
    let grabOffsetWorld = { x: 0, y: 0 };

    const eventToMapPoint = (e) => {
        const rect = mapCanvas.getBoundingClientRect();
        return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };

    mapCanvas.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.stopPropagation();
        dragging = true;

        const p = eventToMapPoint(e);
        const insideFov = lastFovRect &&
            p.x >= lastFovRect.x && p.x <= lastFovRect.x + lastFovRect.w &&
            p.y >= lastFovRect.y && p.y <= lastFovRect.y + lastFovRect.h;

        if (insideFov) {
            // Drag the FoV rect: keep the pointer-to-center offset
            const fovCenterWorld = mapPointToWorld(
                lastFovRect.x + lastFovRect.w / 2,
                lastFovRect.y + lastFovRect.h / 2
            );
            const pointerWorld = mapPointToWorld(p.x, p.y);
            grabOffsetWorld = {
                x: fovCenterWorld.x - pointerWorld.x,
                y: fovCenterWorld.y - pointerWorld.y
            };
        } else {
            // Click anywhere: jump-center the view there, then drag
            grabOffsetWorld = { x: 0, y: 0 };
            const w = mapPointToWorld(p.x, p.y);
            centerViewOnWorldPoint(w.x, w.y);
        }
    });

    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const p = eventToMapPoint(e);
        const w = mapPointToWorld(p.x, p.y);
        centerViewOnWorldPoint(w.x + grabOffsetWorld.x, w.y + grabOffsetWorld.y);
    });

    document.addEventListener('mouseup', () => {
        dragging = false;
    });
}

function applyVisibility(visible) {
    const panel = getPanel();
    const toggleBtn = document.getElementById('minimap-toggle-btn');
    if (!panel) return;
    panel.classList.toggle('hidden', !visible);
    if (toggleBtn) {
        toggleBtn.classList.toggle('active', visible);
        toggleBtn.title = visible ? 'Hide minimap' : 'Show minimap';
    }
    localStorage.setItem(VISIBLE_STORAGE_KEY, visible ? '1' : '0');
    if (visible) refreshMinimap();
}

export function initMinimap() {
    const panel = getPanel();
    const mapCanvas = getMapCanvas();
    const container = getCanvasContainer();
    if (!panel || !mapCanvas || !container) return;

    // Toggle button (visibility persisted in localStorage, default visible)
    const stored = localStorage.getItem(VISIBLE_STORAGE_KEY);
    applyVisibility(stored === null ? true : stored === '1');

    const toggleBtn = document.getElementById('minimap-toggle-btn');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => applyVisibility(!isVisible()));
    }

    // FoV tracks the main canvas scroll and any zoom change
    container.addEventListener('scroll', refreshMinimap, { passive: true });
    onViewportChange(refreshMinimap);

    setupMinimapPanning(mapCanvas);

    refreshMinimap();
}
