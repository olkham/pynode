// Viewport module: owns canvas zoom state and client<->canvas coordinate
// transforms.
//
// Zoom mechanism: a CSS transform `scale(k)` (origin 0 0) on #canvas-viewport,
// the wrapper that contains BOTH the connections SVG (#canvas) and the HTML
// nodes layer (#nodes-container). Nodes are HTML divs, so an SVG viewBox
// could only scale the wires - the wrapper transform scales both layers
// uniformly and keeps native scroll panning working (the scrollable overflow
// of .canvas-container follows the transformed bounding box).
//
// Coordinate spaces:
// - "canvas" coords: untransformed pixels in the 5000x5000 world. Node x/y,
//   SVG path data and grid snapping all live here.
// - "client" coords: browser viewport pixels (mouse events, HTML overlays
//   such as the mini palette, context menus and the selection box).
// Every conversion between the two must go through clientToCanvas /
// canvasToClient below so the zoom factor is applied exactly once.

export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 2.0;
export const ZOOM_STEP = 0.1;

let zoom = 1;

// Listeners notified after any zoom / programmatic view change (minimap etc.)
const viewportListeners = [];

export function onViewportChange(listener) {
    viewportListeners.push(listener);
}

function notifyViewportChange() {
    viewportListeners.forEach(listener => {
        try {
            listener();
        } catch (err) {
            console.error('viewport listener failed:', err);
        }
    });
}

function getViewportEl() {
    // Fall back to the nodes layer (same origin, scale 1) if the zoom root
    // is ever missing so coordinate conversions never throw.
    return document.getElementById('canvas-viewport')
        || document.getElementById('nodes-container');
}

export function getCanvasContainer() {
    return document.querySelector('.canvas-container');
}

export function getZoom() {
    return zoom;
}

/**
 * Convert a client (mouse) position to canvas coordinates.
 */
export function clientToCanvas(clientX, clientY) {
    const rect = getViewportEl().getBoundingClientRect();
    return {
        x: (clientX - rect.left) / zoom,
        y: (clientY - rect.top) / zoom
    };
}

/**
 * Convert canvas coordinates to a client (viewport pixel) position.
 */
export function canvasToClient(x, y) {
    const rect = getViewportEl().getBoundingClientRect();
    return {
        x: rect.left + x * zoom,
        y: rect.top + y * zoom
    };
}

function clampZoom(k) {
    // Round to avoid floating point drift from repeated +/- steps
    const rounded = Math.round(k * 100) / 100;
    return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, rounded));
}

function applyZoomStyles() {
    const viewportEl = getViewportEl();
    if (viewportEl) {
        viewportEl.style.transform = `scale(${zoom})`;
    }
    // Keep the container's background grid in sync with the 20px node grid
    const container = getCanvasContainer();
    if (container) {
        container.style.backgroundSize = `${20 * zoom}px ${20 * zoom}px`;
    }
    const readout = document.getElementById('zoom-reset-btn');
    if (readout) {
        readout.textContent = `${Math.round(zoom * 100)}%`;
    }
}

/**
 * Set the zoom level. If an anchor client position is given (e.g. the mouse
 * cursor for ctrl+wheel), the canvas point under that position stays put by
 * adjusting the container scroll; otherwise the view center is used.
 */
export function setZoom(k, anchorClientX, anchorClientY) {
    const container = getCanvasContainer();
    if (!container || !getViewportEl()) return;

    const newZoom = clampZoom(k);
    if (newZoom === zoom) return;

    const containerRect = container.getBoundingClientRect();
    const ax = anchorClientX !== undefined
        ? anchorClientX
        : containerRect.left + container.clientWidth / 2;
    const ay = anchorClientY !== undefined
        ? anchorClientY
        : containerRect.top + container.clientHeight / 2;

    // Canvas point currently under the anchor (at the old zoom)
    const anchorCanvas = clientToCanvas(ax, ay);

    zoom = newZoom;
    applyZoomStyles();

    // Scroll so the anchor canvas point is back under the anchor client point
    container.scrollLeft = anchorCanvas.x * zoom - (ax - containerRect.left);
    container.scrollTop = anchorCanvas.y * zoom - (ay - containerRect.top);

    notifyViewportChange();
}

export function zoomIn(anchorClientX, anchorClientY) {
    setZoom(zoom + ZOOM_STEP, anchorClientX, anchorClientY);
}

export function zoomOut(anchorClientX, anchorClientY) {
    setZoom(zoom - ZOOM_STEP, anchorClientX, anchorClientY);
}

export function resetZoom() {
    setZoom(1);
}

/**
 * Capture the current view (zoom + scroll) for per-workflow tab caching.
 */
export function captureView() {
    const container = getCanvasContainer();
    return {
        zoom: zoom,
        scrollLeft: container ? container.scrollLeft : 0,
        scrollTop: container ? container.scrollTop : 0
    };
}

/**
 * Restore a view captured by captureView(). Passing null/undefined keeps the
 * current (global) zoom and scroll untouched.
 */
export function restoreView(view) {
    if (!view) return;
    const container = getCanvasContainer();
    if (typeof view.zoom === 'number' && !Number.isNaN(view.zoom)) {
        zoom = clampZoom(view.zoom);
    }
    applyZoomStyles();
    if (container) {
        container.scrollLeft = view.scrollLeft || 0;
        container.scrollTop = view.scrollTop || 0;
    }
    notifyViewportChange();
}

/**
 * Wire up zoom inputs: ctrl+wheel (cursor-anchored) and the +/-/reset
 * buttons in the canvas controls bar.
 */
export function initViewport() {
    const container = getCanvasContainer();
    if (!container) return;

    // Ctrl+wheel (and trackpad pinch, which reports ctrlKey) zooms centered
    // on the cursor. Plain wheel keeps native scrolling.
    container.addEventListener('wheel', (e) => {
        if (!e.ctrlKey) return;
        e.preventDefault();
        if (e.deltaY < 0) {
            zoomIn(e.clientX, e.clientY);
        } else if (e.deltaY > 0) {
            zoomOut(e.clientX, e.clientY);
        }
    }, { passive: false });

    const zoomInBtn = document.getElementById('zoom-in-btn');
    const zoomOutBtn = document.getElementById('zoom-out-btn');
    const zoomResetBtn = document.getElementById('zoom-reset-btn');
    if (zoomInBtn) zoomInBtn.addEventListener('click', () => zoomIn());
    if (zoomOutBtn) zoomOutBtn.addEventListener('click', () => zoomOut());
    if (zoomResetBtn) zoomResetBtn.addEventListener('click', resetZoom);

    applyZoomStyles();
}
