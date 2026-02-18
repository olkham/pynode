// Debug panel and SSE handling
import { API_BASE } from './config.js';

const MAX_DEBUG_MESSAGES = 100; // Maximum number of messages to keep in UI
let messageIdCounter = 0; // Unique ID counter for message elements

const debugState = {
    messageMap: new Map(), // For collapsing similar messages
    showInfo: true,
    showErrors: true,
    collapseSimilar: false
};

export function startDebugPolling() {
    const eventSource = new EventSource(`${API_BASE}/debug/stream`);
    
    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            if (data.type === 'messages' && data.data.length > 0) {
                displayDebugMessages(data.data);
            } else if (data.type === 'errors' && data.data.length > 0) {
                displayErrorMessages(data.data);
            } else if (data.type === 'frame') {
                updateImageViewer(data.nodeId, data.data);
            } else if (data.type === 'rate') {
                updateRateDisplay(data.nodeId, data.display);
            } else if (data.type === 'queue_length') {
                updateQueueLengthDisplay(data.nodeId, data.display);
            } else if (data.type === 'counter') {
                updateCounterDisplay(data.nodeId, data.display);
            } else if (data.type === 'upload_progress') {
                // Handle upload progress updates
                const progressEl = document.getElementById(`progress-${data.upload_id}`);
                if (progressEl) {
                    const fill = progressEl.querySelector('.upload-progress-fill');
                    const label = progressEl.querySelector('.upload-progress-percent');
                    if (fill) fill.style.width = `${data.progress_percent}%`;
                    if (label) label.textContent = `${Math.round(data.progress_percent)}%`;
                }
            } else if (data.type === 'upload_complete') {
                const progressEl = document.getElementById(`progress-${data.upload_id}`);
                if (progressEl) {
                    setTimeout(() => progressEl.remove(), 1000);
                }
            } else if (data.type === 'upload_error') {
                const progressEl = document.getElementById(`progress-${data.upload_id}`);
                if (progressEl) {
                    progressEl.remove();
                }
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

export function updateImageViewer(nodeId, frameData) {
    const imgEl = document.getElementById(`viewer-${nodeId}`);
    if (!imgEl) return;
    
    if (frameData.format === 'jpeg' && frameData.encoding === 'base64') {
        imgEl.src = `data:image/jpeg;base64,${frameData.data}`;
    }
}

export function displayDebugMessages(messages) {
    const container = document.getElementById('debug-messages');
    
    messages.forEach(msg => {
        const messageKey = `${msg.node}:${JSON.stringify(msg.output)}`;

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

export function displayErrorMessages(errors) {
    const container = document.getElementById('debug-messages');
    
    // Don't process or scroll if errors are hidden
    if (!debugState.showErrors) {
        return;
    }
    
    errors.forEach(error => {
        const messageKey = `error:${error.source_node_name}:${error.message}`;
        
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
    
    // Store reference to the element
    messageData.element = msgEl;
    
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
    
    // Render output as collapsible tree
    const outputHtml = renderOutputTree(messageData.output, messageData.isError);
    
    msgEl.innerHTML = `
        <div class="debug-message-header">
            <span class="debug-timestamp">${messageData.timestamp}</span>
            <span class="${nodeClass}">[${messageData.node}]</span>
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
        
        // Scroll node into view
        const canvasContainer = document.querySelector('.canvas-container');
        const nodeRect = nodeEl.getBoundingClientRect();
        const containerRect = canvasContainer.getBoundingClientRect();
        
        // Calculate scroll position to center the node
        const scrollX = nodeEl.offsetLeft - (containerRect.width / 2) + (nodeRect.width / 2);
        const scrollY = nodeEl.offsetTop - (containerRect.height / 2) + (nodeRect.height / 2);
        
        canvasContainer.scrollTo({
            left: scrollX,
            top: scrollY,
            behavior: 'smooth'
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
    
    if (isError && !debugState.showErrors) {
        msgEl.classList.add('hidden');
    } else if (!isError && !debugState.showInfo) {
        msgEl.classList.add('hidden');
    } else {
        msgEl.classList.remove('hidden');
    }
}

function applyAllFilters() {
    const messages = document.querySelectorAll('.debug-message');
    messages.forEach(msgEl => applyFiltersToMessage(msgEl));
}

export function toggleInfoMessages(show) {
    debugState.showInfo = show;
    applyAllFilters();
}

export function toggleErrorMessages(show) {
    debugState.showErrors = show;
    applyAllFilters();
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
            msgEl.remove();
        }
    }
}

export function clearDebug() {
    document.getElementById('debug-messages').innerHTML = '';
    debugState.messageMap.clear();
}
