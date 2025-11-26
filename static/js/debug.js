// Debug panel and SSE handling
import { API_BASE } from './config.js';

const MAX_DEBUG_MESSAGES = 100; // Maximum number of messages to keep in UI
const debugState = {
    messageMap: new Map(), // For collapsing similar messages
    showInfo: true,
    showErrors: true,
    collapseSimilar: true
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
                key: messageKey,
                node: msg.node,
                nodeId: msg.node_id,
                output: msg.output,
                timestamp: msg.timestamp,
                count: 1,
                isError: false
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
                key: messageKey,
                node: error.source_node_name,
                nodeId: error.source_node_id,
                output: error.message,
                timestamp: new Date(error.timestamp * 1000).toLocaleTimeString(),
                count: 1,
                isError: true
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
    msgEl.dataset.messageKey = messageData.key;
    msgEl.dataset.nodeId = messageData.nodeId;
    msgEl.dataset.isError = messageData.isError;
    
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
    const msgEl = document.querySelector(`[data-message-key="${messageData.key}"]`);
    if (msgEl) {
        updateMessageContent(msgEl, messageData);
    }
}

function updateMessageContent(msgEl, messageData) {
    const countBadge = messageData.count > 1 ? `<span class="debug-count">${messageData.count}</span>` : '';
    const icon = messageData.isError ? '⚠️' : '';
    const nodeClass = messageData.isError ? 'debug-node error-node' : 'debug-node';
    const outputClass = messageData.isError ? 'debug-output error-output' : 'debug-output';
    
    msgEl.innerHTML = `
        <div class="debug-message-header">
            <span class="debug-timestamp">${messageData.timestamp}</span>
            <span class="${nodeClass}">[${messageData.node}]</span>
            ${countBadge}
        </div>
        <div class="${outputClass}">${icon} ${typeof messageData.output === 'string' ? messageData.output : JSON.stringify(messageData.output, null, 2)}</div>
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
            const messageKey = messages[i].dataset.messageKey;
            if (messageKey) {
                debugState.messageMap.delete(messageKey);
            }
            messages[i].remove();
        }
    }
}

export function clearDebug() {
    document.getElementById('debug-messages').innerHTML = '';
    debugState.messageMap.clear();
}
