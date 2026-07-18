// Debug panel and SSE handling
import { API_BASE } from './config.js';
import { state } from './state.js';

const MAX_DEBUG_MESSAGES = 100; // Maximum number of messages to keep in UI
let messageIdCounter = 0; // Unique ID counter for message elements

const debugState = {
    messageMap: new Map(), // For collapsing similar messages
    // Single buffer of every message shown in the panel (across all flows).
    // Each entry is the messageData object also referenced by the DOM
    // element it rendered to. Messages are never removed from here when
    // switching flows - only hidden/shown at render time via CSS - so
    // switching back to a flow re-reveals its history. See
    // applyFiltersToMessage()/refilterDebugByWorkflow().
    buffer: [],
    showInfo: true,
    showErrors: true,
    collapseSimilar: false,
    paused: false, // When true, new debug/error messages are not added to the list
    // 'current': show only messages tagged with state.activeWorkflowId.
    // 'all': show every message regardless of origin flow.
    flowFilterMode: 'current'
};

export function startDebugPolling() {
    // EventSource cannot send headers, so the API key (if any) goes in the
    // query string. window.pynodeApiKey is installed by js/auth.js.
    const apiKey = (window.pynodeApiKey && window.pynodeApiKey()) || '';
    const streamUrl = `${API_BASE}/debug/stream` +
        (apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : '');
    const eventSource = new EventSource(streamUrl);

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);

            // Every message/error is kept (tagged with its origin flow) so
            // the "All flows" view and re-filtering on flow switch both work
            // from one buffer - see displayDebugMessages/displayErrorMessages.
            if (data.type === 'messages' && data.data.length > 0) {
                displayDebugMessages(data.data, data.workflowId);
            } else if (data.type === 'errors' && data.data.length > 0) {
                displayErrorMessages(data.data, data.workflowId);
            } else if (data.type === 'frame') {
                updateImageViewer(data.nodeId, data.data);
            } else if (data.type === 'rate') {
                updateRateDisplay(data.nodeId, data.display);
            } else if (data.type === 'queue_length') {
                updateQueueLengthDisplay(data.nodeId, data.display);
            } else if (data.type === 'counter') {
                updateCounterDisplay(data.nodeId, data.display);
            } else if (data.type === 'video_position') {
                updateVideoPosition(data.nodeId, data);
            }
        } catch (error) {
            console.error('Error processing SSE message:', error);
        }
    };
    
    eventSource.onerror = (error) => {
        console.error('SSE connection error:', error);
    };
    
    window.debugEventSource = eventSource;
}

export function updateRateDisplay(nodeId, displayText) {
    const rateEl = document.getElementById(`rate-${nodeId}`);
    if (rateEl) {
        rateEl.textContent = displayText;
    }
}

export function updateQueueLengthDisplay(nodeId, displayText) {
    const queueEl = document.getElementById(`queue-${nodeId}`);
    if (queueEl) {
        queueEl.textContent = displayText;
    }
}

export function updateCounterDisplay(nodeId, displayText) {
    const counterEl = document.getElementById(`counter-${nodeId}`);
    if (counterEl) {
        counterEl.textContent = displayText;
    }
}

export function updateVideoPosition(nodeId, data) {
    const posEl = document.getElementById(`transport-pos-${nodeId}`);
    const sliderEl = document.getElementById(`transport-progress-${nodeId}`);
    const total = data.total > 0 ? data.total : 0;
    const frame = data.frame ?? 0;
    if (posEl) {
        // Zero-pad the current frame to the total's digit count so the label
        // width (and therefore the node width) stays constant as the frame
        // number gains digits (e.g. 003/600 -> 010/600 -> 100/600).
        const current = frame + 1;
        const currentText = total > 0
            ? String(current).padStart(String(total).length, '0')
            : String(current);
        posEl.textContent = `${currentText}/${total > 0 ? total : '?'}`;
        posEl.title = data.playing ? 'Playing' : 'Paused / stopped';
    }
    // Keep the scrub slider in sync unless the user is currently dragging it.
    if (sliderEl && sliderEl.dataset.seeking !== 'true') {
        sliderEl.max = total > 0 ? total - 1 : 0;
        sliderEl.value = frame;
    }
}

export function updateImageViewer(nodeId, frameData) {
    const imgEl = document.getElementById(`viewer-${nodeId}`);
    if (!imgEl) return;
    
    if (frameData.format === 'jpeg' && frameData.encoding === 'base64') {
        imgEl.src = `data:image/jpeg;base64,${frameData.data}`;
    }
}

export function displayDebugMessages(messages, wfId) {
    // While paused, drop incoming messages so the user can inspect the list
    // without it scrolling. Node UI displays (frames, rates, counters) keep
    // updating - only the debug message list is frozen.
    if (debugState.paused) {
        return;
    }

    const container = document.getElementById('debug-messages');

    messages.forEach(msg => {
        // Per-message workflowId (set on the DebugNode entry itself) wins
        // over the SSE envelope's workflowId, but both should always agree.
        const msgWfId = msg.workflowId ?? wfId ?? null;
        const messageKey = `${msgWfId || 'none'}:${msg.node}:${JSON.stringify(msg.output)}`;

        if (debugState.collapseSimilar && debugState.messageMap.has(messageKey)) {
            // Update existing message count
            const existingData = debugState.messageMap.get(messageKey);
            existingData.count++;
            existingData.timestamp = msg.timestamp;
            updateMessageElement(existingData);
        } else {
            // Create new message
            const messageData = {
                id: `msg-${++messageIdCounter}`,
                key: messageKey,
                node: msg.node,
                nodeId: msg.node_id,
                wfId: msgWfId,
                output: msg.output,
                timestamp: msg.timestamp,
                count: 1,
                isError: false,
                display_key: msg.display_key || '',
                element: null // Will be set when element is created
            };

            if (debugState.collapseSimilar) {
                debugState.messageMap.set(messageKey, messageData);
            }

            createMessageElement(messageData, container);
        }
    });

    // Limit number of messages
    trimDebugMessages(container);

    container.scrollTop = container.scrollHeight;
}

export function displayErrorMessages(errors, wfId) {
    // While paused, freeze the list (see displayDebugMessages).
    if (debugState.paused) {
        return;
    }

    const container = document.getElementById('debug-messages');

    // Don't process or scroll if errors are hidden
    if (!debugState.showErrors) {
        return;
    }

    errors.forEach(error => {
        const msgWfId = error.workflowId ?? wfId ?? null;
        const messageKey = `error:${msgWfId || 'none'}:${error.source_node_name}:${error.message}`;

        if (debugState.collapseSimilar && debugState.messageMap.has(messageKey)) {
            // Update existing error count
            const existingData = debugState.messageMap.get(messageKey);
            existingData.count++;
            existingData.timestamp = new Date(error.timestamp * 1000).toLocaleTimeString();
            updateMessageElement(existingData);
        } else {
            // Create new error message
            const messageData = {
                id: `msg-${++messageIdCounter}`,
                key: messageKey,
                node: error.source_node_name,
                nodeId: error.source_node_id,
                wfId: msgWfId,
                output: error.message,
                timestamp: new Date(error.timestamp * 1000).toLocaleTimeString(),
                count: 1,
                isError: true,
                element: null // Will be set when element is created
            };

            if (debugState.collapseSimilar) {
                debugState.messageMap.set(messageKey, messageData);
            }

            createMessageElement(messageData, container);
        }
    });

    // Limit number of messages
    trimDebugMessages(container);
    
    container.scrollTop = container.scrollHeight;
}

function createMessageElement(messageData, container) {
    const msgEl = document.createElement('div');
    msgEl.className = messageData.isError ? 'debug-message error-message' : 'debug-message';
    msgEl.id = messageData.id;
    msgEl.dataset.nodeId = messageData.nodeId;
    msgEl.dataset.isError = messageData.isError;
    msgEl.dataset.wfId = messageData.wfId || '';

    // Store reference to the element
    messageData.element = msgEl;

    // Add to the single cross-flow buffer (never forked per-flow - see
    // applyFiltersToMessage/refilterDebugByWorkflow for how flow scoping is
    // applied at render/re-render time instead).
    debugState.buffer.push(messageData);

    updateMessageContent(msgEl, messageData);

    // Make message clickable to jump to node
    msgEl.addEventListener('click', () => {
        jumpToNode(messageData.nodeId);
    });

    // Apply filters
    applyFiltersToMessage(msgEl);

    container.appendChild(msgEl);
}

function updateMessageElement(messageData) {
    // Use stored element reference instead of querySelector
    if (messageData.element) {
        updateMessageContent(messageData.element, messageData);
    }
}

// Get type label for a value
function getTypeLabel(value) {
    if (value === null) return 'null';
    if (value === undefined) return 'undefined';
    if (Array.isArray(value)) return `array[${value.length}]`;
    if (typeof value === 'object') return 'object';
    return typeof value;
}

// Render a value as a collapsible tree (compact single-line style)
function renderTreeValue(value, key = null, depth = 0) {
    if (value === null) {
        return `<span class="tv-null">null</span>`;
    }
    if (value === undefined) {
        return `<span class="tv-undefined">undefined</span>`;
    }
    if (typeof value === 'boolean') {
        return `<span class="tv-bool">${value}</span>`;
    }
    if (typeof value === 'number') {
        return `<span class="tv-num">${value}</span>`;
    }
    if (typeof value === 'string') {
        const maxLen = 100;
        const displayStr = value.length > maxLen ? value.substring(0, maxLen) + '...' : value;
        const escaped = displayStr.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        return `<span class="tv-str" title="${value.length > maxLen ? value.length + ' chars' : ''}">"${escaped}"</span>`;
    }
    
    if (Array.isArray(value)) {
        if (value.length === 0) {
            return `<span class="tv-empty">[]</span>`;
        }
        let childrenHtml = '';
        value.forEach((item, index) => {
            const typeLabel = getTypeLabel(item);
            const isExpandable = item !== null && typeof item === 'object';
            if (isExpandable) {
                childrenHtml += `<div class="ti c" style="margin-left:${(depth+1)*8}px"><span class="tt" onclick="event.stopPropagation();this.parentElement.classList.toggle('c')">▶</span><span class="tk">${index}</span>: <span class="tl">${typeLabel}</span><div class="tc">${renderTreeChildren(item, depth+1)}</div></div>`;
            } else {
                childrenHtml += `<div class="ti" style="margin-left:${(depth+1)*8}px"><span class="tk">${index}</span>: ${renderTreeValue(item, index, depth+1)}</div>`;
            }
        });
        return childrenHtml;
    }
    
    if (typeof value === 'object') {
        const keys = Object.keys(value);
        if (keys.length === 0) {
            return `<span class="tv-empty">{}</span>`;
        }
        let childrenHtml = '';
        keys.forEach(k => {
            const v = value[k];
            const typeLabel = getTypeLabel(v);
            const isExpandable = v !== null && typeof v === 'object';
            const escaped = k.replace(/</g, '&lt;').replace(/>/g, '&gt;');
            if (isExpandable) {
                childrenHtml += `<div class="ti c" style="margin-left:${(depth+1)*8}px"><span class="tt" onclick="event.stopPropagation();this.parentElement.classList.toggle('c')">▶</span><span class="tk">${escaped}</span>: <span class="tl">${typeLabel}</span><div class="tc">${renderTreeChildren(v, depth+1)}</div></div>`;
            } else {
                childrenHtml += `<div class="ti" style="margin-left:${(depth+1)*8}px"><span class="tk">${escaped}</span>: ${renderTreeValue(v, k, depth+1)}</div>`;
            }
        });
        return childrenHtml;
    }
    
    return `<span class="tv">${String(value)}</span>`;
}

// Render children of an object/array
function renderTreeChildren(value, depth) {
    if (Array.isArray(value)) {
        let html = '';
        value.forEach((item, index) => {
            const typeLabel = getTypeLabel(item);
            const isExpandable = item !== null && typeof item === 'object';
            if (isExpandable) {
                html += `<div class="ti c" style="margin-left:${(depth+1)*8}px"><span class="tt" onclick="event.stopPropagation();this.parentElement.classList.toggle('c')">▶</span><span class="tk">${index}</span>: <span class="tl">${typeLabel}</span><div class="tc">${renderTreeChildren(item, depth+1)}</div></div>`;
            } else {
                html += `<div class="ti" style="margin-left:${(depth+1)*8}px"><span class="tk">${index}</span>: ${renderTreeValue(item, index, depth+1)}</div>`;
            }
        });
        return html;
    }
    if (typeof value === 'object' && value !== null) {
        let html = '';
        Object.keys(value).forEach(k => {
            const v = value[k];
            const typeLabel = getTypeLabel(v);
            const isExpandable = v !== null && typeof v === 'object';
            const escaped = k.replace(/</g, '&lt;').replace(/>/g, '&gt;');
            if (isExpandable) {
                html += `<div class="ti c" style="margin-left:${(depth+1)*8}px"><span class="tt" onclick="event.stopPropagation();this.parentElement.classList.toggle('c')">▶</span><span class="tk">${escaped}</span>: <span class="tl">${typeLabel}</span><div class="tc">${renderTreeChildren(v, depth+1)}</div></div>`;
            } else {
                html += `<div class="ti" style="margin-left:${(depth+1)*8}px"><span class="tk">${escaped}</span>: ${renderTreeValue(v, k, depth+1)}</div>`;
            }
        });
        return html;
    }
    return renderTreeValue(value, null, depth);
}

// Render the complete message output as a tree
function renderOutputTree(output, isError) {
    if (output === null || output === undefined) {
        return `<span class="tv-null">${output}</span>`;
    }
    if (typeof output !== 'object') {
        return renderTreeValue(output);
    }
    
    const icon = isError ? '⚠️ ' : '';
    let html = icon + '<div class="tree-root">';
    
    if (Array.isArray(output)) {
        output.forEach((item, index) => {
            const typeLabel = getTypeLabel(item);
            const isExpandable = item !== null && typeof item === 'object';
            if (isExpandable) {
                html += `<div class="ti c"><span class="tt" onclick="event.stopPropagation();this.parentElement.classList.toggle('c')">▶</span><span class="tk">${index}</span>: <span class="tl">${typeLabel}</span><div class="tc">${renderTreeChildren(item, 0)}</div></div>`;
            } else {
                html += `<div class="ti"><span class="tk">${index}</span>: ${renderTreeValue(item, index, 0)}</div>`;
            }
        });
    } else {
        Object.keys(output).forEach(key => {
            const v = output[key];
            const typeLabel = getTypeLabel(v);
            const isExpandable = v !== null && typeof v === 'object';
            const escaped = key.replace(/</g, '&lt;').replace(/>/g, '&gt;');
            if (isExpandable) {
                html += `<div class="ti c"><span class="tt" onclick="event.stopPropagation();this.parentElement.classList.toggle('c')">▶</span><span class="tk">${escaped}</span>: <span class="tl">${typeLabel}</span><div class="tc">${renderTreeChildren(v, 0)}</div></div>`;
            } else {
                html += `<div class="ti"><span class="tk">${escaped}</span>: ${renderTreeValue(v, key, 0)}</div>`;
            }
        });
    }
    
    html += '</div>';
    return html;
}

function updateMessageContent(msgEl, messageData) {
    const countBadge = messageData.count > 1 ? `<span class="debug-count">${messageData.count}</span>` : '';
    const nodeClass = messageData.isError ? 'debug-node error-node' : 'debug-node';
    const outputClass = messageData.isError ? 'debug-output error-output' : 'debug-output';

    // Show display_key (e.g. "msg.payload") before node name in header, if present
    const keyLabel = messageData.display_key ? `<span class="debug-key">${messageData.display_key}</span> ` : '';

    // Per-message flow label - only visible in "All flows" mode (see the
    // #debug-messages.show-flow-labels rule in style.css) so mixed origins
    // are distinguishable without cluttering the default "Current flow" view.
    const flowName = messageData.wfId
        ? (state.workflows.get(messageData.wfId)?.name || messageData.wfId)
        : '(no flow)';
    const flowBadge = `<span class="debug-flow-badge" title="Flow: ${flowName}">${flowName}</span>`;

    // Render output as collapsible tree
    const outputHtml = renderOutputTree(messageData.output, messageData.isError);

    msgEl.innerHTML = `
        <div class="debug-message-header">
            <span class="debug-timestamp">${messageData.timestamp}</span>
            <span class="${nodeClass}">[${messageData.node}]</span>
            ${flowBadge}
            ${countBadge}
        </div>
        ${keyLabel ? `<div class="debug-key-label">${keyLabel}:</div>` : ''}
        <div class="${outputClass}">${outputHtml}</div>
    `;
}

function jumpToNode(nodeId) {
    if (!nodeId) return;
    
    const nodeEl = document.getElementById(`node-${nodeId}`);
    if (!nodeEl) return;
    
    // Deselect all nodes first
    import('./selection.js').then(({ deselectAllNodes, selectNode }) => {
        deselectAllNodes();
        selectNode(nodeId);

        // Scroll node into view. offsetLeft/offsetWidth are canvas
        // (untransformed) px; scroll offsets are in zoomed px, so scale.
        const canvasContainer = document.querySelector('.canvas-container');
        const containerRect = canvasContainer.getBoundingClientRect();

        import('./viewport.js').then(({ getZoom }) => {
            const zoom = getZoom();
            const nodeCenterX = nodeEl.offsetLeft + nodeEl.offsetWidth / 2;
            const nodeCenterY = nodeEl.offsetTop + nodeEl.offsetHeight / 2;

            // Calculate scroll position to center the node
            const scrollX = nodeCenterX * zoom - containerRect.width / 2;
            const scrollY = nodeCenterY * zoom - containerRect.height / 2;

            canvasContainer.scrollTo({
                left: scrollX,
                top: scrollY,
                behavior: 'smooth'
            });
        });

        // Flash effect
        nodeEl.style.animation = 'none';
        setTimeout(() => {
            nodeEl.style.animation = 'flash 0.5s ease-in-out 2';
        }, 10);
    });
}

function applyFiltersToMessage(msgEl) {
    const isError = msgEl.dataset.isError === 'true';
    const wfId = msgEl.dataset.wfId || null;

    let hidden = false;
    if (isError && !debugState.showErrors) {
        hidden = true;
    } else if (!isError && !debugState.showInfo) {
        hidden = true;
    } else if (debugState.flowFilterMode === 'current') {
        // "Current flow" mode: show only messages tagged with the active
        // flow. Messages with no workflow id (backward-compat / produced
        // outside any flow) belong to no specific flow, so they're excluded
        // here and only surface in "All flows" mode.
        hidden = !wfId || wfId !== state.activeWorkflowId;
    }

    msgEl.classList.toggle('hidden', hidden);
}

// Re-applies both the info/error toggles and the flow-scope filter to every
// message currently in the buffer. Called whenever a filter that affects
// visibility changes (info/error toggle, flow-filter mode, active workflow
// switch) - the buffer itself is never mutated, only what's shown is.
function applyAllFilters() {
    debugState.buffer.forEach(messageData => {
        if (messageData.element) applyFiltersToMessage(messageData.element);
    });
}

/**
 * Switch the debug panel between "current flow" and "all flows" scoping.
 * Re-filters the existing buffer in place - nothing is deleted or re-fetched.
 */
export function setDebugFlowFilterMode(mode) {
    debugState.flowFilterMode = mode === 'all' ? 'all' : 'current';
    const container = document.getElementById('debug-messages');
    if (container) {
        container.classList.toggle('show-flow-labels', debugState.flowFilterMode === 'all');
    }
    applyAllFilters();
}

export function getDebugFlowFilterMode() {
    return debugState.flowFilterMode;
}

/**
 * Re-filter the existing message buffer against the (new) active workflow.
 * Call this after switching flows so old messages from the flow just left
 * hide again and the newly-active flow's history reappears - no messages
 * are deleted, only their visibility changes.
 */
export function refilterDebugByWorkflow() {
    applyAllFilters();
}

export function toggleInfoMessages(show) {
    debugState.showInfo = show;
    applyAllFilters();
}

export function toggleErrorMessages(show) {
    debugState.showErrors = show;
    applyAllFilters();
}

/**
 * Toggle the paused state of the debug list. When paused, new debug/error
 * messages are dropped (not rendered) so the current view stays put.
 * Returns the new paused state.
 */
export function toggleDebugPaused() {
    debugState.paused = !debugState.paused;
    return debugState.paused;
}

export function isDebugPaused() {
    return debugState.paused;
}

export function toggleCollapseSimilar(collapse) {
    debugState.collapseSimilar = collapse;
    
    if (!collapse) {
        // Clear the message map and reset all counts to 1
        debugState.messageMap.clear();
        const messages = document.querySelectorAll('.debug-message');
        messages.forEach(msgEl => {
            const countBadge = msgEl.querySelector('.debug-count');
            if (countBadge) {
                countBadge.remove();
            }
        });
    }
}

function trimDebugMessages(container) {
    const messages = container.querySelectorAll('.debug-message');
    if (messages.length > MAX_DEBUG_MESSAGES) {
        const removeCount = messages.length - MAX_DEBUG_MESSAGES;
        for (let i = 0; i < removeCount; i++) {
            const msgEl = messages[i];
            // Find and remove from messageMap by element reference
            for (const [key, data] of debugState.messageMap.entries()) {
                if (data.element === msgEl) {
                    debugState.messageMap.delete(key);
                    break;
                }
            }
            // Also drop it from the cross-flow buffer so it doesn't linger
            // there once its DOM element is gone.
            const bufferIdx = debugState.buffer.findIndex(data => data.element === msgEl);
            if (bufferIdx !== -1) debugState.buffer.splice(bufferIdx, 1);

            msgEl.remove();
        }
    }
}

export function clearDebug() {
    document.getElementById('debug-messages').innerHTML = '';
    debugState.messageMap.clear();
    debugState.buffer = [];
}
