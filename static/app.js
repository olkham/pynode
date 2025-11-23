// PyNode Frontend Application
// Handles UI interactions, node management, and API communication

const API_BASE = 'http://localhost:5000/api';

// State management
const state = {
    nodes: new Map(),
    connections: [],
    selectedNode: null,
    selectedNodes: new Set(),
    draggingNode: null,
    drawingConnection: null,
    nodeTypes: [],
    selectionBox: null,
    selectionStart: null,
    isModified: false  // Track if workflow has unsaved changes
};

// Set modified state and update deploy button
function setModified(modified) {
    state.isModified = modified;
    const deployBtn = document.getElementById('deploy-btn');
    if (deployBtn) {
        deployBtn.disabled = !modified;
    }
}

// Show toast notification
function showToast(message, duration = 3000) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('show');
    
    setTimeout(() => {
        toast.classList.remove('show');
    }, duration);
}

// Mark a node as modified
function markNodeModified(nodeId) {
    const nodeEl = document.getElementById(`node-${nodeId}`);
    if (nodeEl) {
        nodeEl.classList.add('modified');
    }
}

// Clear all node modified indicators
function clearAllNodeModifiedIndicators() {
    document.querySelectorAll('.node.modified').forEach(nodeEl => {
        nodeEl.classList.remove('modified');
    });
}

// Initialize the application
document.addEventListener('DOMContentLoaded', async () => {
    await loadNodeTypes();
    setupEventListeners();
    await loadWorkflow();
    startDebugPolling();
});

// Load available node types from API
async function loadNodeTypes() {
    try {
        const response = await fetch(`${API_BASE}/node-types`);
        state.nodeTypes = await response.json();
        renderNodePalette();
    } catch (error) {
        console.error('Failed to load node types:', error);
    }
}

// Render node palette
function renderNodePalette() {
    const palette = document.getElementById('node-palette');
    palette.innerHTML = '';
    
    // Group nodes by category
    const categories = {
        'input': { title: 'Input', nodes: [] },
        'output': { title: 'Output', nodes: [] },
        'function': { title: 'Function', nodes: [] },
        'logic': { title: 'Logic', nodes: [] },
        'custom': { title: 'Custom', nodes: [] }
    };
    
    state.nodeTypes.forEach(nodeType => {
        const category = nodeType.category || 'custom';
        if (categories[category]) {
            categories[category].nodes.push(nodeType);
        } else {
            categories['custom'].nodes.push(nodeType);
        }
    });
    
    // Render each category
    Object.entries(categories).forEach(([key, category]) => {
        if (category.nodes.length === 0) return;
        
        const categoryEl = document.createElement('div');
        categoryEl.className = 'palette-category';
        
        const headerEl = document.createElement('div');
        headerEl.className = 'palette-category-header';
        headerEl.textContent = category.title;
        categoryEl.appendChild(headerEl);
        
        const listEl = document.createElement('div');
        listEl.className = 'palette-category-list';
        
        category.nodes.forEach(nodeType => {
            const nodeEl = document.createElement('div');
            nodeEl.className = 'palette-node';
            
            const icon = nodeType.icon || '◆';
            const inputCount = nodeType.inputCount !== undefined ? nodeType.inputCount : 1;
            const outputCount = nodeType.outputCount !== undefined ? nodeType.outputCount : 1;
            
            const portsHtml = `
                <div class="palette-node-ports">
                    ${inputCount > 0 ? '<div class="palette-port input"></div>' : ''}
                    ${outputCount > 0 ? '<div class="palette-port output"></div>' : ''}
                </div>
            `;
            
            nodeEl.innerHTML = `
                <span class="palette-node-icon">${icon}</span>
                <span class="palette-node-name">${nodeType.name}</span>
                ${portsHtml}
            `;
            nodeEl.draggable = true;
            
            // Apply node colors to palette item
            if (nodeType.color) {
                nodeEl.style.backgroundColor = nodeType.color;
            }
            if (nodeType.borderColor) {
                nodeEl.style.borderColor = nodeType.borderColor;
            }
            if (nodeType.textColor) {
                nodeEl.style.color = nodeType.textColor;
            }
            
            nodeEl.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('nodeType', nodeType.type);
            });
            
            listEl.appendChild(nodeEl);
        });
        
        categoryEl.appendChild(listEl);
        palette.appendChild(categoryEl);
    });
}

// Setup event listeners
function setupEventListeners() {
    const canvas = document.getElementById('canvas');
    const nodesContainer = document.getElementById('nodes-container');
    
    // Canvas drop event for creating nodes
    nodesContainer.addEventListener('dragover', (e) => e.preventDefault());
    nodesContainer.addEventListener('drop', handleCanvasDrop);
    
    // Header buttons
    document.getElementById('deploy-btn').addEventListener('click', deployWorkflow);
    document.getElementById('clear-btn').addEventListener('click', clearWorkflow);
    document.getElementById('export-btn').addEventListener('click', exportWorkflow);
    document.getElementById('import-btn').addEventListener('click', importWorkflow);
    document.getElementById('clear-debug-btn').addEventListener('click', clearDebug);
    
    // Canvas click to deselect
    nodesContainer.addEventListener('click', (e) => {
        if (e.target === nodesContainer) {
            deselectNode();
        }
    });
    
    // Keyboard delete and escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            deselectAllNodes();
        }
        
        if (e.key === 'Delete' && state.selectedNodes.size > 0) {
            // Delete all selected nodes
            const nodesToDelete = Array.from(state.selectedNodes);
            nodesToDelete.forEach(nodeId => deleteNode(nodeId));
            deselectAllNodes();
        }
    });
    
    // Canvas selection box
    const canvasContainer = document.querySelector('.canvas-container');
    const canvasEl = document.getElementById('canvas');
    
    canvasContainer.addEventListener('mousedown', (e) => {
        // Only start selection box if clicking on canvas or connections, not on nodes
        const isNode = e.target.closest('.node');
        const isPort = e.target.classList.contains('port');
        
        if (isNode || isPort) return;
        
        if (!e.ctrlKey && !e.metaKey) {
            deselectAllNodes();
        }
        
        state.selectionStart = { x: e.clientX, y: e.clientY };
        state.selectionBox = document.createElement('div');
        state.selectionBox.className = 'selection-box';
        state.selectionBox.style.left = `${e.clientX}px`;
        state.selectionBox.style.top = `${e.clientY}px`;
        state.selectionBox.style.width = '0';
        state.selectionBox.style.height = '0';
        document.body.appendChild(state.selectionBox);
        
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!state.selectionBox || !state.selectionStart) return;
        
        const currentX = e.clientX;
        const currentY = e.clientY;
        const startX = state.selectionStart.x;
        const startY = state.selectionStart.y;
        
        const left = Math.min(startX, currentX);
        const top = Math.min(startY, currentY);
        const width = Math.abs(currentX - startX);
        const height = Math.abs(currentY - startY);
        
        state.selectionBox.style.left = `${left}px`;
        state.selectionBox.style.top = `${top}px`;
        state.selectionBox.style.width = `${width}px`;
        state.selectionBox.style.height = `${height}px`;
        
        // Track which nodes are currently in the selection box
        const nodesInBox = new Set();
        
        state.nodes.forEach((nodeData, nodeId) => {
            const nodeEl = document.getElementById(`node-${nodeId}`);
            if (!nodeEl) return;
            
            const rect = nodeEl.getBoundingClientRect();
            const boxLeft = left;
            const boxTop = top;
            const boxRight = left + width;
            const boxBottom = top + height;
            
            // Check if node intersects with selection box
            if (rect.left < boxRight && rect.right > boxLeft && 
                rect.top < boxBottom && rect.bottom > boxTop) {
                nodesInBox.add(nodeId);
            }
        });
        
        // Update selection to match nodes in box
        nodesInBox.forEach(nodeId => {
            if (!state.selectedNodes.has(nodeId)) {
                state.selectedNodes.add(nodeId);
                const nodeEl = document.getElementById(`node-${nodeId}`);
                if (nodeEl) nodeEl.classList.add('selected');
            }
        });
    });
    
    document.addEventListener('mouseup', () => {
        if (state.selectionBox) {
            state.selectionBox.remove();
            state.selectionBox = null;
            state.selectionStart = null;
        }
    });
}

// Handle dropping a node type onto canvas
async function handleCanvasDrop(e) {
    e.preventDefault();
    const nodeType = e.dataTransfer.getData('nodeType');
    if (!nodeType) return;
    
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    await createNode(nodeType, x, y);
}

// Create a new node
// Save node position to backend
async function saveNodePosition(nodeId, x, y) {
    try {
        await fetch(`${API_BASE}/nodes/${nodeId}/position`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ x, y })
        });
    } catch (error) {
        console.error('Failed to save node position:', error);
    }
}

async function createNode(type, x, y) {
    try {
        // Get node type info for display name
        const nodeType = state.nodeTypes.find(nt => nt.type === type);
        const displayName = nodeType ? nodeType.name : type;
        
        const response = await fetch(`${API_BASE}/nodes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                type: type,
                name: displayName,
                config: {}
            })
        });
        
        const nodeData = await response.json();
        nodeData.x = x;
        nodeData.y = y;
        
        // Get color info and metadata from node type
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
        
        // Save initial position
        await saveNodePosition(nodeData.id, x, y);
        markNodeModified(nodeData.id);
        setModified(true);
    } catch (error) {
        console.error('Failed to create node:', error);
    }
}

// Render a node on the canvas
function renderNode(nodeData) {
    const nodeEl = document.createElement('div');
    nodeEl.className = 'node';
    nodeEl.id = `node-${nodeData.id}`;
    nodeEl.style.left = `${nodeData.x}px`;
    nodeEl.style.top = `${nodeData.y}px`;
    
    // Apply custom colors if available
    if (nodeData.color) {
        nodeEl.style.backgroundColor = nodeData.color;
    }
    if (nodeData.borderColor) {
        nodeEl.style.borderColor = nodeData.borderColor;
    }
    if (nodeData.textColor) {
        nodeEl.style.color = nodeData.textColor;
    }
    
    const inputCount = nodeData.inputCount !== undefined ? nodeData.inputCount : 1;
    const outputCount = nodeData.outputCount !== undefined ? nodeData.outputCount : 1;
    const icon = nodeData.icon || '◆';
    
    // Determine layout: input-only, output-only, or passthrough
    let nodeContent = '';
    if (inputCount === 0 && outputCount > 0) {
        // Input node: [Icon][Node Name]-
        nodeContent = `
            <div class="node-content">
                <div class="node-icon-container"><div class="node-icon">${icon}</div></div>
                <div class="node-title">${nodeData.name}</div>
            </div>
        `;
    } else if (inputCount > 0 && outputCount === 0) {
        // Output node: -[Node Name][Icon]
        nodeContent = `
            <div class="node-content">
                <div class="node-title">${nodeData.name}</div>
                <div class="node-icon-container"><div class="node-icon">${icon}</div></div>
            </div>
        `;
    } else {
        // Passthrough node: -[Icon][Node Name]-
        nodeContent = `
            <div class="node-content">
                <div class="node-icon-container"><div class="node-icon">${icon}</div></div>
                <div class="node-title">${nodeData.name}</div>
            </div>
        `;
    }
    
    const portsHtml = (inputCount > 0 || outputCount > 0) ? `
        <div class="node-ports">
            ${inputCount > 0 ? `<div class="port input" data-node="${nodeData.id}" data-type="input"></div>` : ''}
            ${outputCount > 0 ? `<div class="port output" data-node="${nodeData.id}" data-type="output"></div>` : ''}
        </div>
    ` : '';
    
    nodeEl.innerHTML = `
        <div class="node-modified-indicator"></div>
        ${nodeContent}
        ${portsHtml}
    `;
    
    // Node dragging
    let isDragging = false;
    let startX, startY;
    
    nodeEl.addEventListener('mousedown', (e) => {
        if (e.target.classList.contains('port')) return;
        
        isDragging = true;
        startX = e.clientX - nodeData.x;
        startY = e.clientY - nodeData.y;
        
        // If clicking on an already selected node without Ctrl, keep the multi-selection
        // If clicking with Ctrl, toggle selection
        // If clicking on unselected node without Ctrl, select only this node
        if (e.ctrlKey || e.metaKey) {
            selectNode(nodeData.id, true);
        } else if (!state.selectedNodes.has(nodeData.id)) {
            selectNode(nodeData.id, false);
        }
        // If already selected and no Ctrl, don't change selection (allows dragging multiple)
        
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        
        const deltaX = (e.clientX - startX) - nodeData.x;
        const deltaY = (e.clientY - startY) - nodeData.y;
        
        // Move all selected nodes
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
        if (isDragging) {
            // Save positions for all selected nodes
            state.selectedNodes.forEach(selectedId => {
                const selectedNodeData = state.nodes.get(selectedId);
                if (selectedNodeData) {
                    saveNodePosition(selectedId, selectedNodeData.x, selectedNodeData.y);
                }
            });
        }
        isDragging = false;
    });
    
    // Port connection handling
    const outputPort = nodeEl.querySelector('.port.output');
    
    if (outputPort) {
        outputPort.addEventListener('mousedown', (e) => {
            e.stopPropagation();
            startConnection(nodeData.id, e);
        });
    }
    
    // Allow connecting by releasing mouse anywhere on the destination node
    nodeEl.addEventListener('mouseup', (e) => {
        if (state.drawingConnection && state.drawingConnection.sourceId !== nodeData.id) {
            e.stopPropagation();
            endConnection(nodeData.id);
        }
    });
    
    document.getElementById('nodes-container').appendChild(nodeEl);
}

// Start drawing a connection
function startConnection(sourceId, e) {
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

// Draw temporary connection line
function drawTempConnection(e) {
    if (!state.drawingConnection) return;
    
    const canvasRect = document.getElementById('canvas').getBoundingClientRect();
    const endX = e.clientX - canvasRect.left - 20; // Offset by -10px left
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

// End connection on target node
async function endConnection(targetId) {
    if (!state.drawingConnection) return;
    
    const sourceId = state.drawingConnection.sourceId;
    
    if (sourceId !== targetId) {
        await createConnection(sourceId, targetId);
    }
    
    cancelConnection();
}

// Cancel connection drawing
function cancelConnection() {
    state.drawingConnection = null;
    document.getElementById('temp-line').innerHTML = '';
    document.removeEventListener('mousemove', drawTempConnection);
    document.removeEventListener('mouseup', cancelConnection);
}

// Create a connection via API
async function createConnection(sourceId, targetId) {
    try {
        const response = await fetch(`${API_BASE}/connections`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source: sourceId,
                target: targetId,
                sourceOutput: 0,
                targetInput: 0
            })
        });
        
        const connection = await response.json();
        state.connections.push(connection);
        renderConnection(connection);
        markNodeModified(connection.source);
        markNodeModified(connection.target);
        setModified(true);
    } catch (error) {
        console.error('Failed to create connection:', error);
    }
}

// Render a connection
function renderConnection(connection) {
    const sourceNode = state.nodes.get(connection.source);
    const targetNode = state.nodes.get(connection.target);
    
    if (!sourceNode || !targetNode) return;
    
    const sourceEl = document.getElementById(`node-${connection.source}`);
    const targetEl = document.getElementById(`node-${connection.target}`);
    
    const sourcePort = sourceEl.querySelector('.port.output');
    const targetPort = targetEl.querySelector('.port.input');
    
    const sourceRect = sourcePort.getBoundingClientRect();
    const targetRect = targetPort.getBoundingClientRect();
    const canvasRect = document.getElementById('canvas').getBoundingClientRect();
    
    const x1 = sourceRect.left + sourceRect.width / 2 - canvasRect.left;
    const y1 = sourceRect.top + sourceRect.height / 2 - canvasRect.top;
    const x2 = targetRect.left + targetRect.width / 2 - canvasRect.left;
    const y2 = targetRect.top + targetRect.height / 2 - canvasRect.top;
    
    // Create a cubic bezier curve that exits and enters perpendicular to the nodes
    const x2End = x2 - 20; // Offset the line end by -20px
    const dx = x2End - x1;
    const controlDistance = Math.abs(dx) * 0.5;
    
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('class', 'connection');
    path.setAttribute('d', `M ${x1} ${y1} C ${x1 + controlDistance} ${y1}, ${x2End - controlDistance} ${y2}, ${x2End} ${y2}`);
    path.setAttribute('marker-end', 'url(#arrowhead)');
    path.setAttribute('data-source', connection.source);
    path.setAttribute('data-target', connection.target);
    
    path.addEventListener('click', async () => {
        if (confirm('Delete this connection?')) {
            await deleteConnection(connection.source, connection.target);
        }
    });
    
    document.getElementById('connections').appendChild(path);
}

// Update all connections (called after node movement)
function updateConnections() {
    document.getElementById('connections').innerHTML = '';
    state.connections.forEach(conn => renderConnection(conn));
}

// Delete a connection
async function deleteConnection(sourceId, targetId) {
    try {
        await fetch(`${API_BASE}/connections`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source: sourceId,
                target: targetId,
                sourceOutput: 0
            })
        });
        
        state.connections = state.connections.filter(
            c => !(c.source === sourceId && c.target === targetId)
        );
        updateConnections();
        markNodeModified(sourceId);
        markNodeModified(targetId);
        setModified(true);
    } catch (error) {
        console.error('Failed to delete connection:', error);
    }
}

// Delete a node
async function deleteNode(nodeId) {
    try {
        await fetch(`${API_BASE}/nodes/${nodeId}`, { method: 'DELETE' });
        
        state.nodes.delete(nodeId);
        state.connections = state.connections.filter(
            c => c.source !== nodeId && c.target !== nodeId
        );
        
        document.getElementById(`node-${nodeId}`).remove();
        updateConnections();
        
        if (state.selectedNode === nodeId) {
            deselectNode();
        }
        setModified(true);
    } catch (error) {
        console.error('Failed to delete node:', error);
    }
}

// Select a node
function selectNode(nodeId, addToSelection = false) {
    if (!addToSelection) {
        deselectAllNodes();
    }
    
    state.selectedNode = nodeId;
    state.selectedNodes.add(nodeId);
    const nodeEl = document.getElementById(`node-${nodeId}`);
    if (nodeEl) nodeEl.classList.add('selected');
    
    const nodeData = state.nodes.get(nodeId);
    if (state.selectedNodes.size === 1) {
        renderProperties(nodeData);
    } else {
        document.getElementById('properties-panel').innerHTML = 
            `<p class="placeholder">${state.selectedNodes.size} nodes selected</p>`;
    }
}

// Deselect node
function deselectNode() {
    if (state.selectedNode) {
        const nodeEl = document.getElementById(`node-${state.selectedNode}`);
        if (nodeEl) nodeEl.classList.remove('selected');
    }
    state.selectedNode = null;
    
    document.getElementById('properties-panel').innerHTML = 
        '<p class="placeholder">Select a node to edit properties</p>';
}

// Deselect all nodes
function deselectAllNodes() {
    state.selectedNodes.forEach(nodeId => {
        const nodeEl = document.getElementById(`node-${nodeId}`);
        if (nodeEl) nodeEl.classList.remove('selected');
    });
    state.selectedNodes.clear();
    state.selectedNode = null;
    
    document.getElementById('properties-panel').innerHTML = 
        '<p class="placeholder">Select a node to edit properties</p>';
}

// Render node properties panel
function renderProperties(nodeData) {
    const panel = document.getElementById('properties-panel');
    
    let html = `
        <div class="property-group">
            <label class="property-label">Name</label>
            <input type="text" class="property-input" value="${nodeData.name}" 
                   onchange="updateNodeProperty('${nodeData.id}', 'name', this.value)">
        </div>
    `;
    
    // Get node type definition
    const nodeType = state.nodeTypes.find(nt => nt.type === nodeData.type);
    if (nodeType && nodeType.properties) {
        nodeType.properties.forEach(prop => {
            html += '<div class="property-group">';
            
            if (prop.type === 'text') {
                html += `
                    <label class="property-label">${prop.label}</label>
                    <input type="text" class="property-input" 
                           value="${nodeData.config[prop.name] || ''}"
                           onchange="updateNodeConfig('${nodeData.id}', '${prop.name}', this.value)">
                `;
            } else if (prop.type === 'textarea') {
                html += `
                    <label class="property-label">${prop.label}</label>
                    <textarea class="property-input property-textarea" 
                              onchange="updateNodeConfig('${nodeData.id}', '${prop.name}', this.value)">${nodeData.config[prop.name] || ''}</textarea>
                `;
            } else if (prop.type === 'select') {
                html += `
                    <label class="property-label">${prop.label}</label>
                    <select class="property-select" 
                            onchange="updateNodeConfig('${nodeData.id}', '${prop.name}', this.value)">
                `;
                prop.options.forEach(option => {
                    const selected = nodeData.config[prop.name] === option.value ? 'selected' : '';
                    html += `<option value="${option.value}" ${selected}>${option.label}</option>`;
                });
                html += '</select>';
            } else if (prop.type === 'button') {
                html += `
                    <button class="btn btn-primary" onclick="triggerNodeAction('${nodeData.id}', '${prop.action}')">${prop.label}</button>
                `;
            }
            
            if (prop.help) {
                html += `<small class="property-help">${prop.help}</small>`;
            }
            
            html += '</div>';
        });
    }
    
    panel.innerHTML = html;
}

// Update node property
async function updateNodeProperty(nodeId, property, value) {
    try {
        const nodeData = state.nodes.get(nodeId);
        nodeData[property] = value;
        
        await fetch(`${API_BASE}/nodes/${nodeId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [property]: value })
        });
        
        // Update UI
        const nodeEl = document.getElementById(`node-${nodeId}`);
        nodeEl.querySelector('.node-title').textContent = value;
    } catch (error) {
        console.error('Failed to update node:', error);
    }
}

// Update node config
async function updateNodeConfig(nodeId, key, value) {
    try {
        const nodeData = state.nodes.get(nodeId);
        nodeData.config[key] = value;
        
        await fetch(`${API_BASE}/nodes/${nodeId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config: nodeData.config })
        });
        markNodeModified(nodeId);
        setModified(true);
    } catch (error) {
        console.error('Failed to update node config:', error);
    }
}

// Trigger node action (generic handler for button actions)
async function triggerNodeAction(nodeId, action) {
    try {
        await fetch(`${API_BASE}/nodes/${nodeId}/${action}`, { method: 'POST' });
    } catch (error) {
        console.error(`Failed to trigger ${action} on node:`, error);
    }
}

// Legacy inject function (kept for backward compatibility)
async function injectNode(nodeId) {
    await triggerNodeAction(nodeId, 'inject');
}

// Load workflow from API
async function loadWorkflow() {
    try {
        const response = await fetch(`${API_BASE}/workflow`);
        const workflow = await response.json();
        
        // Clear current state
        state.nodes.clear();
        state.connections = [];
        document.getElementById('nodes-container').innerHTML = '';
        document.getElementById('connections').innerHTML = '';
        
        // Load nodes
        workflow.nodes.forEach(nodeData => {
            // Use stored position or default to (100, 100)
            nodeData.x = nodeData.x !== undefined ? nodeData.x : 100;
            nodeData.y = nodeData.y !== undefined ? nodeData.y : 100;
            
            // Always get metadata from node type (backend doesn't store visual properties)
            const nodeType = state.nodeTypes.find(nt => nt.type === nodeData.type);
            
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
        });
        
        // Load connections
        workflow.connections.forEach(conn => {
            state.connections.push(conn);
            renderConnection(conn);
        });
        
        // Clear modified state after loading
        setModified(false);
    } catch (error) {
        console.error('Failed to load workflow:', error);
    }
}

// Deploy workflow
async function deployWorkflow() {
    try {
        // Just save the workflow to disk without re-importing
        const response = await fetch(`${API_BASE}/workflow/save`, {
            method: 'POST'
        });
        
        if (response.ok) {
            clearAllNodeModifiedIndicators();
            setModified(false);
            showToast('Workflow deployed and saved!');
        } else {
            throw new Error('Failed to save workflow');
        }
    } catch (error) {
        console.error('Failed to deploy workflow:', error);
        showToast('Failed to deploy workflow');
    }
}

// Clear workflow
async function clearWorkflow() {
    if (!confirm('Clear all nodes and connections?')) return;
    
    const nodeIds = Array.from(state.nodes.keys());
    for (const nodeId of nodeIds) {
        await deleteNode(nodeId);
    }
}

// Export workflow
async function exportWorkflow() {
    try {
        const response = await fetch(`${API_BASE}/workflow`);
        const workflow = await response.json();
        
        const dataStr = JSON.stringify(workflow, null, 2);
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(dataBlob);
        
        const link = document.createElement('a');
        link.href = url;
        link.download = 'workflow.json';
        link.click();
    } catch (error) {
        console.error('Failed to export workflow:', error);
    }
}

// Import workflow
function importWorkflow() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/json';
    
    input.onchange = async (e) => {
        const file = e.target.files[0];
        const text = await file.text();
        const workflow = JSON.parse(text);
        
        try {
            await fetch(`${API_BASE}/workflow`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(workflow)
            });
            
            await loadWorkflow();
        } catch (error) {
            console.error('Failed to import workflow:', error);
        }
    };
    
    input.click();
}

// Setup SSE for real-time debug messages
function startDebugPolling() {
    const eventSource = new EventSource(`${API_BASE}/debug/stream`);
    
    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            if (data.type === 'messages' && data.data.length > 0) {
                displayDebugMessages(data.data);
            }
        } catch (error) {
            console.error('Error processing debug message:', error);
        }
    };
    
    eventSource.onerror = (error) => {
        console.error('SSE connection error:', error);
        // Will automatically reconnect
    };
    
    // Store reference to close on cleanup if needed
    window.debugEventSource = eventSource;
}

// Display debug messages
function displayDebugMessages(messages) {
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
    
    // Auto-scroll to bottom
    container.scrollTop = container.scrollHeight;
}

// Clear debug messages
function clearDebug() {
    document.getElementById('debug-messages').innerHTML = '';
}
