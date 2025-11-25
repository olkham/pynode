// Debug panel and SSE handling
import { API_BASE } from './config.js';

const MAX_DEBUG_MESSAGES = 100; // Maximum number of messages to keep in UI

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
        const msgEl = document.createElement('div');
        msgEl.className = 'debug-message';
        msgEl.innerHTML = `
            <span class="debug-timestamp">${msg.timestamp}</span>
            <span class="debug-node">[${msg.node}]</span>
            <div class="debug-output">${JSON.stringify(msg.output, null, 2)}</div>
        `;
        container.appendChild(msgEl);
    });
    
    // Limit number of messages
    trimDebugMessages(container);
    
    container.scrollTop = container.scrollHeight;
}

export function displayErrorMessages(errors) {
    const container = document.getElementById('debug-messages');
    
    errors.forEach(error => {
        const msgEl = document.createElement('div');
        msgEl.className = 'debug-message error-message';
        
        const timestamp = new Date(error.timestamp * 1000).toLocaleTimeString();
        
        msgEl.innerHTML = `
            <span class="debug-timestamp">${timestamp}</span>
            <span class="debug-node error-node">[${error.source_node_name}]</span>
            <div class="debug-output error-output">⚠️ ${error.message}</div>
        `;
        container.appendChild(msgEl);
    });
    
    // Limit number of messages
    trimDebugMessages(container);
    
    container.scrollTop = container.scrollHeight;
}

function trimDebugMessages(container) {
    const messages = container.querySelectorAll('.debug-message');
    if (messages.length > MAX_DEBUG_MESSAGES) {
        const removeCount = messages.length - MAX_DEBUG_MESSAGES;
        for (let i = 0; i < removeCount; i++) {
            messages[i].remove();
        }
    }
}

export function clearDebug() {
    document.getElementById('debug-messages').innerHTML = '';
}
