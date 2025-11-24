// Connection management
import { state, markNodeModified, setModified } from './state.js';

export function createConnection(sourceId, targetId, sourceOutput = 0, targetInput = 0) {
    const connection = {
        source: sourceId,
        target: targetId,
        sourceOutput: sourceOutput,
        targetInput: targetInput
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
    
    // Get the correct output port based on index
    const outputPorts = sourceEl.querySelectorAll('.port.output');
    const sourcePort = outputPorts[connection.sourceOutput || 0] || sourceEl.querySelector('.port.output');
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
    
    const pathData = `M ${x1} ${y1} C ${x1 + controlDistance} ${y1}, ${x2End - controlDistance} ${y2}, ${x2End} ${y2}`;
    
    // Create invisible wider path for easier clicking
    const hitArea = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    hitArea.setAttribute('d', pathData);
    hitArea.setAttribute('stroke', 'transparent');
    hitArea.setAttribute('stroke-width', '20');
    hitArea.setAttribute('fill', 'none');
    hitArea.setAttribute('data-source', connection.source);
    hitArea.setAttribute('data-target', connection.target);
    hitArea.setAttribute('data-source-output', connection.sourceOutput || 0);
    hitArea.style.cursor = 'pointer';
    
    // Create visible path
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('class', 'connection');
    path.setAttribute('d', pathData);
    path.setAttribute('marker-end', 'url(#arrowhead)');
    path.setAttribute('data-source', connection.source);
    path.setAttribute('data-target', connection.target);
    path.setAttribute('data-source-output', connection.sourceOutput || 0);
    path.style.pointerEvents = 'none';
    
    // Check if this connection is selected
    if (state.selectedConnection && 
        state.selectedConnection.source === connection.source &&
        state.selectedConnection.target === connection.target &&
        state.selectedConnection.sourceOutput === (connection.sourceOutput || 0)) {
        path.classList.add('selected');
        console.log('Added selected class to connection:', connection.source, '->', connection.target);
    }
    
    // Add click handler to hit area
    hitArea.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        console.log('Connection clicked:', connection);
        selectConnection(connection.source, connection.target, connection.sourceOutput || 0);
        
        // Prevent canvas click from deselecting immediately
        import('./state.js').then(({ state }) => {
            state.justSelectedConnection = true;
            setTimeout(() => {
                state.justSelectedConnection = false;
            }, 100);
        });
    });
    
    // Check if this connection is selected
    if (state.selectedConnection && 
        state.selectedConnection.source === connection.source &&
        state.selectedConnection.target === connection.target &&
        state.selectedConnection.sourceOutput === (connection.sourceOutput || 0)) {
        path.classList.add('selected');
    }
    
    // Append both hit area and visible path
    document.getElementById('connections').appendChild(hitArea);
    document.getElementById('connections').appendChild(path);
}

export function updateConnections() {
    document.getElementById('connections').innerHTML = '';
    state.connections.forEach(conn => renderConnection(conn));
}

export function deleteConnection(sourceId, targetId, sourceOutput = null) {
    state.connections = state.connections.filter(
        c => !(c.source === sourceId && c.target === targetId && 
               (sourceOutput === null || c.sourceOutput === sourceOutput))
    );
    updateConnections();
    markNodeModified(sourceId);
    markNodeModified(targetId);
    setModified(true);
}

export function startConnection(sourceId, e, outputIndex = 0) {
    const sourceNode = document.getElementById(`node-${sourceId}`);
    const outputPorts = sourceNode.querySelectorAll('.port.output');
    const port = outputPorts[outputIndex] || sourceNode.querySelector('.port.output');
    
    if (!port) return;
    
    const rect = port.getBoundingClientRect();
    const canvasRect = document.getElementById('canvas').getBoundingClientRect();
    
    state.drawingConnection = {
        sourceId: sourceId,
        outputIndex: outputIndex,
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
    const outputIndex = state.drawingConnection.outputIndex || 0;
    
    if (sourceId !== targetId) {
        createConnection(sourceId, targetId, outputIndex, 0);
    }
    
    cancelConnection();
}

export function cancelConnection() {
    state.drawingConnection = null;
    document.getElementById('temp-line').innerHTML = '';
    document.removeEventListener('mousemove', drawTempConnection);
    document.removeEventListener('mouseup', cancelConnection);
}

export function selectConnection(sourceId, targetId, sourceOutput = 0) {
    console.log('selectConnection called:', sourceId, targetId, sourceOutput);
    
    // Deselect any selected nodes
    import('./selection.js').then(({ deselectAllNodes }) => {
        deselectAllNodes();
    });
    
    // Store selected connection
    state.selectedConnection = {
        source: sourceId,
        target: targetId,
        sourceOutput: sourceOutput
    };
    
    console.log('Selected connection state:', state.selectedConnection);
    
    // Update visual state
    updateConnections();
}

export function deselectConnection() {
    if (state.selectedConnection) {
        state.selectedConnection = null;
        updateConnections();
    }
}

export function deleteSelectedConnection() {
    if (state.selectedConnection) {
        deleteConnection(
            state.selectedConnection.source,
            state.selectedConnection.target,
            state.selectedConnection.sourceOutput
        );
        state.selectedConnection = null;
    }
}
