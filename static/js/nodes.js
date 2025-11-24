// Node rendering and management
import { API_BASE } from './config.js';
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
    
    // Calculate and apply dynamic height based on output count
    if (outputCount > 1) {
        // Base height (30px) + additional height for extra ports
        // Each port is 10px + 4px gap, need at least 14px per port after the first
        const extraHeight = (outputCount - 1) * 14;
        const totalHeight = 30 + extraHeight;
        nodeEl.style.minHeight = `${totalHeight}px`;
    }
    const icon = nodeData.icon || '◆';
    
    // Build node content HTML
    let nodeContent = buildNodeContent(nodeData, icon, inputCount, outputCount);
    
    // Generate ports HTML with support for multiple outputs
    let portsHtml = '';
    if (inputCount > 0 || outputCount > 0) {
        const inputPortsHtml = inputCount > 0 ? `<div class="port input" data-node="${nodeData.id}" data-type="input" data-index="0"></div>` : '';
        
        let outputPortsHtml = '';
        if (outputCount > 0) {
            if (outputCount === 1) {
                outputPortsHtml = `<div class="port output" data-node="${nodeData.id}" data-type="output" data-index="0"></div>`;
            } else {
                // Multiple outputs - stack them vertically
                outputPortsHtml = '<div class="output-ports-container">';
                for (let i = 0; i < outputCount; i++) {
                    outputPortsHtml += `<div class="port output" data-node="${nodeData.id}" data-type="output" data-index="${i}"></div>`;
                }
                outputPortsHtml += '</div>';
            }
        }
        
        portsHtml = `
            <div class="node-ports">
                ${inputPortsHtml}
                ${outputPortsHtml}
            </div>
        `;
    }
    
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
        if (nodeData.type === 'DebugNode') {
            const isEnabled = nodeData.debugEnabled !== undefined ? nodeData.debugEnabled : true;
            return `
                <div class="node-content">
                    <div class="node-title">${nodeData.name}</div>
                    <div class="node-icon-container"><div class="node-icon">${icon}</div></div>
                    <label class="gate-switch">
                        <input type="checkbox" id="debug-${nodeData.id}" ${isEnabled ? 'checked' : ''} 
                               onchange="window.toggleDebug('${nodeData.id}', this.checked)">
                        <span class="gate-slider"></span>
                    </label>
                </div>
            `;
        } else {
            return `
                <div class="node-content">
                    <div class="node-title">${nodeData.name}</div>
                    <div class="node-icon-container"><div class="node-icon">${icon}</div></div>
                </div>
            `;
        }
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
    
    // Port connection handling - support multiple output ports
    const outputPorts = nodeEl.querySelectorAll('.port.output');
    outputPorts.forEach(outputPort => {
        outputPort.addEventListener('mousedown', (e) => {
            e.stopPropagation();
            const outputIndex = parseInt(outputPort.getAttribute('data-index') || '0');
            // Import dynamically to avoid circular dependency
            import('./connections.js').then(({ startConnection }) => {
                startConnection(nodeData.id, e, outputIndex);
            });
        });
    });
    
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

export function updateNodeOutputCount(nodeId, outputCount) {
    const nodeData = state.nodes.get(nodeId);
    if (!nodeData) return;
    
    // Update the output count
    nodeData.outputCount = outputCount;
    
    // Re-render the node
    const nodeEl = document.getElementById(`node-${nodeId}`);
    if (nodeEl) {
        nodeEl.remove();
        renderNode(nodeData);
        updateConnections();
    }
}

// Toggle debug node enabled state
window.toggleDebug = async function(nodeId, enabled) {
    const nodeData = state.nodes.get(nodeId);
    if (!nodeData) return;
    
    const newEnabled = enabled;
    
    try {
        const response = await fetch(`${API_BASE}/nodes/${nodeId}/debug-enabled`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: newEnabled })
        });
        
        if (response.ok) {
            nodeData.debugEnabled = newEnabled;
        }
    } catch (error) {
        console.error('Failed to toggle debug state:', error);
    }
};
