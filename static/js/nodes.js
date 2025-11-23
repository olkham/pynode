// Node rendering and management
import { state, generateNodeId, markNodeModified, setModified } from './state.js';
import { updateConnections } from './connections.js';
import { selectNode } from './selection.js';

export function createNode(type, x, y) {
    const nodeType = state.nodeTypes.find(nt => nt.type === type);
    const displayName = nodeType ? nodeType.name : type;
    
    const nodeData = {
        id: generateNodeId(),
        type: type,
        name: displayName,
        config: {},
        x: x,
        y: y
    };
    
    if (nodeType) {
        nodeData.color = nodeType.color;
        nodeData.borderColor = nodeType.borderColor;
        nodeData.textColor = nodeType.textColor;
        nodeData.icon = nodeType.icon;
        nodeData.inputCount = nodeType.inputCount;
        nodeData.outputCount = nodeType.outputCount;
    }
    
    state.nodes.set(nodeData.id, nodeData);
    renderNode(nodeData);
    markNodeModified(nodeData.id);
    setModified(true);
}

export function renderNode(nodeData) {
    const nodeEl = document.createElement('div');
    nodeEl.className = 'node';
    nodeEl.id = `node-${nodeData.id}`;
    nodeEl.style.left = `${nodeData.x}px`;
    nodeEl.style.top = `${nodeData.y}px`;
    
    // Apply custom colors
    if (nodeData.color) nodeEl.style.backgroundColor = nodeData.color;
    if (nodeData.borderColor) nodeEl.style.borderColor = nodeData.borderColor;
    if (nodeData.textColor) nodeEl.style.color = nodeData.textColor;
    
    const inputCount = nodeData.inputCount !== undefined ? nodeData.inputCount : 1;
    const outputCount = nodeData.outputCount !== undefined ? nodeData.outputCount : 1;
    const icon = nodeData.icon || '◆';
    
    // Build node content HTML
    let nodeContent = buildNodeContent(nodeData, icon, inputCount, outputCount);
    
    const portsHtml = (inputCount > 0 || outputCount > 0) ? `
        <div class="node-ports">
            ${inputCount > 0 ? `<div class="port input" data-node="${nodeData.id}" data-type="input"></div>` : ''}
            ${outputCount > 0 ? `<div class="port output" data-node="${nodeData.id}" data-type="output"></div>` : ''}
        </div>
    ` : '';
    
    let imageViewerHtml = '';
    if (nodeData.type === 'ImageViewerNode') {
        const width = nodeData.config?.width || 320;
        const height = nodeData.config?.height || 240;
        imageViewerHtml = `
            <div class="image-viewer-container" style="width: ${width}px; height: ${height}px;">
                <img id="viewer-${nodeData.id}" class="image-viewer-frame" alt="No frame" />
            </div>
        `;
    }
    
    nodeEl.innerHTML = `
        <div class="node-modified-indicator"></div>
        ${nodeContent}
        ${portsHtml}
        ${imageViewerHtml}
    `;
    
    attachNodeEventHandlers(nodeEl, nodeData);
    document.getElementById('nodes-container').appendChild(nodeEl);
}

function buildNodeContent(nodeData, icon, inputCount, outputCount) {
    if (inputCount === 0 && outputCount > 0) {
        return `
            <div class="node-content">
                <div class="node-icon-container"><div class="node-icon">${icon}</div></div>
                <div class="node-title">${nodeData.name}</div>
            </div>
        `;
    } else if (inputCount > 0 && outputCount === 0) {
        return `
            <div class="node-content">
                <div class="node-title">${nodeData.name}</div>
                <div class="node-icon-container"><div class="node-icon">${icon}</div></div>
            </div>
        `;
    } else {
        if (nodeData.type === 'GateNode') {
            const isOpen = nodeData.gateOpen !== undefined ? nodeData.gateOpen : true;
            return `
                <div class="node-content">
                    <div class="node-icon-container"><div class="node-icon">${icon}</div></div>
                    <div class="node-title">${nodeData.name}</div>
                    <label class="gate-switch">
                        <input type="checkbox" id="gate-${nodeData.id}" ${isOpen ? 'checked' : ''} 
                               onchange="window.toggleGate('${nodeData.id}', this.checked)">
                        <span class="gate-slider"></span>
                    </label>
                </div>
            `;
        } else {
            return `
                <div class="node-content">
                    <div class="node-icon-container"><div class="node-icon">${icon}</div></div>
                    <div class="node-title">${nodeData.name}</div>
                </div>
            `;
        }
    }
}

function attachNodeEventHandlers(nodeEl, nodeData) {
    let isDragging = false;
    let startX, startY;
    
    nodeEl.addEventListener('mousedown', (e) => {
        if (e.target.classList.contains('port')) return;
        
        isDragging = true;
        startX = e.clientX - nodeData.x;
        startY = e.clientY - nodeData.y;
        
        if (e.ctrlKey || e.metaKey) {
            selectNode(nodeData.id, true);
        } else if (!state.selectedNodes.has(nodeData.id)) {
            selectNode(nodeData.id, false);
        }
        
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        
        const deltaX = (e.clientX - startX) - nodeData.x;
        const deltaY = (e.clientY - startY) - nodeData.y;
        
        state.selectedNodes.forEach(selectedId => {
            const selectedNodeData = state.nodes.get(selectedId);
            const selectedNodeEl = document.getElementById(`node-${selectedId}`);
            if (selectedNodeData && selectedNodeEl) {
                selectedNodeData.x += deltaX;
                selectedNodeData.y += deltaY;
                selectedNodeEl.style.left = `${selectedNodeData.x}px`;
                selectedNodeEl.style.top = `${selectedNodeData.y}px`;
            }
        });
        
        nodeData.x = e.clientX - startX;
        nodeData.y = e.clientY - startY;
        
        updateConnections();
    });
    
    document.addEventListener('mouseup', () => {
        isDragging = false;
    });
    
    // Port connection handling
    const outputPort = nodeEl.querySelector('.port.output');
    if (outputPort) {
        outputPort.addEventListener('mousedown', (e) => {
            e.stopPropagation();
            // Import dynamically to avoid circular dependency
            import('./connections.js').then(({ startConnection }) => {
                startConnection(nodeData.id, e);
            });
        });
    }
    
    nodeEl.addEventListener('mouseup', (e) => {
        if (state.drawingConnection && state.drawingConnection.sourceId !== nodeData.id) {
            e.stopPropagation();
            import('./connections.js').then(({ endConnection }) => {
                endConnection(nodeData.id);
            });
        }
    });
}

export function deleteNode(nodeId) {
    state.nodes.delete(nodeId);
    state.connections = state.connections.filter(
        c => c.source !== nodeId && c.target !== nodeId
    );
    
    document.getElementById(`node-${nodeId}`)?.remove();
    updateConnections();
    
    if (state.selectedNode === nodeId) {
        import('./selection.js').then(({ deselectNode }) => deselectNode());
    }
    setModified(true);
}
