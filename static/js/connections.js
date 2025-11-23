// Connection management
import { state, markNodeModified, setModified } from './state.js';

export function createConnection(sourceId, targetId) {
    const connection = {
        source: sourceId,
        target: targetId,
        sourceOutput: 0,
        targetInput: 0
    };
    
    state.connections.push(connection);
    renderConnection(connection);
    markNodeModified(sourceId);
    markNodeModified(targetId);
    setModified(true);
}

export function renderConnection(connection) {
    const sourceNode = state.nodes.get(connection.source);
    const targetNode = state.nodes.get(connection.target);
    
    if (!sourceNode || !targetNode) return;
    
    const sourceEl = document.getElementById(`node-${connection.source}`);
    const targetEl = document.getElementById(`node-${connection.target}`);
    
    if (!sourceEl || !targetEl) return;
    
    const sourcePort = sourceEl.querySelector('.port.output');
    const targetPort = targetEl.querySelector('.port.input');
    
    if (!sourcePort || !targetPort) return;
    
    const sourceRect = sourcePort.getBoundingClientRect();
    const targetRect = targetPort.getBoundingClientRect();
    const canvasRect = document.getElementById('canvas').getBoundingClientRect();
    
    const x1 = sourceRect.left + sourceRect.width / 2 - canvasRect.left;
    const y1 = sourceRect.top + sourceRect.height / 2 - canvasRect.top;
    const x2 = targetRect.left + targetRect.width / 2 - canvasRect.left;
    const y2 = targetRect.top + targetRect.height / 2 - canvasRect.top;
    
    const x2End = x2 - 20;
    const dx = x2End - x1;
    const controlDistance = Math.abs(dx) * 0.5;
    
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('class', 'connection');
    path.setAttribute('d', `M ${x1} ${y1} C ${x1 + controlDistance} ${y1}, ${x2End - controlDistance} ${y2}, ${x2End} ${y2}`);
    path.setAttribute('marker-end', 'url(#arrowhead)');
    path.setAttribute('data-source', connection.source);
    path.setAttribute('data-target', connection.target);
    
    path.addEventListener('click', () => {
        if (confirm('Delete this connection?')) {
            deleteConnection(connection.source, connection.target);
        }
    });
    
    document.getElementById('connections').appendChild(path);
}

export function updateConnections() {
    document.getElementById('connections').innerHTML = '';
    state.connections.forEach(conn => renderConnection(conn));
}

export function deleteConnection(sourceId, targetId) {
    state.connections = state.connections.filter(
        c => !(c.source === sourceId && c.target === targetId)
    );
    updateConnections();
    markNodeModified(sourceId);
    markNodeModified(targetId);
    setModified(true);
}

export function startConnection(sourceId, e) {
    const sourceNode = document.getElementById(`node-${sourceId}`);
    const port = sourceNode.querySelector('.port.output');
    const rect = port.getBoundingClientRect();
    const canvasRect = document.getElementById('canvas').getBoundingClientRect();
    
    state.drawingConnection = {
        sourceId: sourceId,
        startX: rect.left + rect.width / 2 - canvasRect.left,
        startY: rect.top + rect.height / 2 - canvasRect.top
    };
    
    document.addEventListener('mousemove', drawTempConnection);
    document.addEventListener('mouseup', cancelConnection);
}

export function drawTempConnection(e) {
    if (!state.drawingConnection) return;
    
    const canvasRect = document.getElementById('canvas').getBoundingClientRect();
    const endX = e.clientX - canvasRect.left - 20;
    const endY = e.clientY - canvasRect.top;
    
    const dx = endX - state.drawingConnection.startX;
    const controlDistance = Math.abs(dx) * 0.5;
    
    const tempLine = document.getElementById('temp-line');
    tempLine.innerHTML = `
        <path d="M ${state.drawingConnection.startX} ${state.drawingConnection.startY} 
                 C ${state.drawingConnection.startX + controlDistance} ${state.drawingConnection.startY},
                   ${endX - controlDistance} ${endY},
                   ${endX} ${endY}"
              stroke="#0e639c" stroke-width="2" fill="none" marker-end="url(#arrowhead)" />
    `;
}

export function endConnection(targetId) {
    if (!state.drawingConnection) return;
    
    const sourceId = state.drawingConnection.sourceId;
    
    if (sourceId !== targetId) {
        createConnection(sourceId, targetId);
    }
    
    cancelConnection();
}

export function cancelConnection() {
    state.drawingConnection = null;
    document.getElementById('temp-line').innerHTML = '';
    document.removeEventListener('mousemove', drawTempConnection);
    document.removeEventListener('mouseup', cancelConnection);
}
