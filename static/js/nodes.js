// Node rendering and management
import { API_BASE } from './config.js';
import { state, generateNodeId, markNodeModified, markNodeAdded, markNodeDeleted, setModified, getNodeType } from './state.js';
import { updateConnections, nodeHasConnections, getConnectionAtPoint, highlightConnectionForInsert, clearConnectionHighlight, getHoveredConnection, insertNodeIntoConnection } from './connections.js';
import { selectNode } from './selection.js';

const GRID_SIZE = 20;

function clampToCanvasBounds(x, y) {
    // Keep nodes within the drawable canvas area (best-effort).
    const min = 0;
    const maxX = 5000;
    const maxY = 5000;
    return {
        x: Math.min(Math.max(x, min), maxX),
        y: Math.min(Math.max(y, min), maxY)
    };
}

function getInputPort0CenterInCanvasCoords(nodeEl) {
    const nodesContainer = document.getElementById('nodes-container');
    if (!nodesContainer) return null;

    const portEl = nodeEl.querySelector('.port.input[data-index="0"]') || nodeEl.querySelector('.port.input');
    if (!portEl) return null;

    const portRect = portEl.getBoundingClientRect();
    const containerRect = nodesContainer.getBoundingClientRect();

    return {
        x: portRect.left + portRect.width / 2 - containerRect.left,
        y: portRect.top + portRect.height / 2 - containerRect.top
    };
}

export function snapNodeToGrid(nodeId, gridSize = GRID_SIZE) {
    const nodeData = state.nodes.get(nodeId);
    const nodeEl = document.getElementById(`node-${nodeId}`);
    if (!nodeData || !nodeEl) return false;

    const portCenter = getInputPort0CenterInCanvasCoords(nodeEl);
    if (!portCenter) return false;

    const snappedX = Math.round(portCenter.x / gridSize) * gridSize;
    const snappedY = Math.round(portCenter.y / gridSize) * gridSize;
    const deltaX = snappedX - portCenter.x;
    const deltaY = snappedY - portCenter.y;

    if (deltaX === 0 && deltaY === 0) return true;

    const next = clampToCanvasBounds(nodeData.x + deltaX, nodeData.y + deltaY);
    nodeData.x = next.x;
    nodeData.y = next.y;
    nodeEl.style.left = `${nodeData.x}px`;
    nodeEl.style.top = `${nodeData.y}px`;
    updateConnections();
    return true;
}

function snapSelectedNodesToGrid(anchorNodeId, gridSize = GRID_SIZE) {
    const anchorEl = document.getElementById(`node-${anchorNodeId}`);
    if (!anchorEl) return;

    const anchorPortCenter = getInputPort0CenterInCanvasCoords(anchorEl);
    if (!anchorPortCenter) return;

    const snappedX = Math.round(anchorPortCenter.x / gridSize) * gridSize;
    const snappedY = Math.round(anchorPortCenter.y / gridSize) * gridSize;
    const deltaX = snappedX - anchorPortCenter.x;
    const deltaY = snappedY - anchorPortCenter.y;

    if (deltaX === 0 && deltaY === 0) return;

    state.selectedNodes.forEach(selectedId => {
        const selectedNodeData = state.nodes.get(selectedId);
        const selectedNodeEl = document.getElementById(`node-${selectedId}`);
        if (!selectedNodeData || !selectedNodeEl) return;

        const next = clampToCanvasBounds(selectedNodeData.x + deltaX, selectedNodeData.y + deltaY);
        selectedNodeData.x = next.x;
        selectedNodeData.y = next.y;
        selectedNodeEl.style.left = `${selectedNodeData.x}px`;
        selectedNodeEl.style.top = `${selectedNodeData.y}px`;
    });

    updateConnections();
}

/**
 * Generate a unique name for a node by checking existing node names
 */
export function generateUniqueName(baseName, nodeType = null) {
    // Extract base name without number suffix (e.g., "debug 2" -> "debug")
    let cleanBaseName = baseName;
    const match = baseName.match(/^(.+?)\s+(\d+)$/);
    if (match) {
        cleanBaseName = match[1];
    }
    
    let uniqueName = cleanBaseName;
    let counter = 1;
    
    // Check if name already exists
    const existingNames = new Set();
    state.nodes.forEach(node => {
        // If nodeType is provided, only check nodes of the same type
        if (!nodeType || node.type === nodeType) {
            existingNames.add(node.name.toLowerCase());
        }
    });
    
    // If base name exists, try with numbers
    while (existingNames.has(uniqueName.toLowerCase())) {
        counter++;
        uniqueName = `${cleanBaseName} ${counter}`;
    }
    
    return uniqueName;
}

export function createNode(type, x, y) {
    const nodeType = getNodeType(type);
    const displayName = nodeType ? nodeType.name : type;
    
    // Generate unique name by checking existing nodes
    const uniqueName = generateUniqueName(displayName, type);

    
    // Save state before creating node
    import('./history.js').then(({ saveState }) => {
        saveState('create node');
    });
    
    const nodeData = {
        id: generateNodeId(),
        type: type,
        name: uniqueName,
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
    markNodeAdded(nodeData.id);
    markNodeModified(nodeData.id);
    setModified(true);
    
    return nodeData.id;
}

// Track z-index for node layering
let nodeZIndex = 1;

export function renderNode(nodeData) {
    const nodeEl = document.createElement('div');
    nodeEl.className = 'node';
    nodeEl.id = `node-${nodeData.id}`;
    nodeEl.style.left = `${nodeData.x}px`;
    nodeEl.style.top = `${nodeData.y}px`;
    nodeEl.style.zIndex = nodeZIndex++;
    
    // Add disabled class if node is disabled
    if (nodeData.enabled === false) {
        nodeEl.classList.add('disabled');
    }
    
    // Apply custom colors
    if (nodeData.color) nodeEl.style.backgroundColor = nodeData.color;
    if (nodeData.borderColor) nodeEl.style.borderColor = nodeData.borderColor;
    if (nodeData.textColor) nodeEl.style.color = nodeData.textColor;
    
    const inputCount = nodeData.inputCount !== undefined ? nodeData.inputCount : 1;
    const outputCount = nodeData.outputCount !== undefined ? nodeData.outputCount : 1;
    
    // Calculate and apply dynamic height based on port count (whichever is larger)
    const maxPorts = Math.max(inputCount, outputCount);
    if (maxPorts > 1) {
        // Base height (30px) + additional height for extra ports
        // Each port is 10px + 4px gap, need at least 14px per port after the first
        const extraHeight = (maxPorts - 1) * 14;
        const totalHeight = 30 + extraHeight;
        nodeEl.style.minHeight = `${totalHeight}px`;
    }
    const icon = nodeData.icon || '◆';
    
    // Build node content HTML
    let nodeContent = buildNodeContent(nodeData, icon, inputCount, outputCount);
    
    // Generate ports HTML with support for multiple inputs and outputs
    let portsHtml = '';
    if (inputCount > 0 || outputCount > 0) {
        let inputPortsHtml = '';
        if (inputCount > 0) {
            if (inputCount === 1) {
                inputPortsHtml = `<div class="port input" data-node="${nodeData.id}" data-type="input" data-index="0"></div>`;
            } else {
                // Multiple inputs - stack them vertically
                inputPortsHtml = '<div class="input-ports-container">';
                for (let i = 0; i < inputCount; i++) {
                    inputPortsHtml += `<div class="port input" data-node="${nodeData.id}" data-type="input" data-index="${i}"></div>`;
                }
                inputPortsHtml += '</div>';
            }
        }
        
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
    const nodeType = getNodeType(nodeData.type);
    const uiComponent = nodeType?.uiComponent;
    const uiConfig = nodeType?.uiComponentConfig || {};
    
    // Build the base content structure
    let contentParts = {
        left: '',
        center: '',
        right: ''
    };
    
    // Icon always in center-left
    contentParts.center = `<div class="node-icon-container"><div class="node-icon">${icon}</div></div>`;
    
    // Title always in center
    contentParts.center += `<div class="node-title">${nodeData.name}</div>`;
    
    // Add UI component based on type
    if (uiComponent === 'button') {
        // Button on the left (like InjectNode)
        const buttonIcon = uiConfig.icon || '▶';
        const action = uiConfig.action || 'inject';
        const tooltip = uiConfig.tooltip || 'Trigger';
        contentParts.left = `<button class="inject-btn" onclick="window.nodeAction('${nodeData.id}', '${action}')" title="${tooltip}">${buttonIcon}</button>`;
    } else if (uiComponent === 'toggle') {
        // Toggle switch on the right (like GateNode, DebugNode, DrawPredictionsNode)
        const action = uiConfig.action || 'toggle';
        const isChecked = nodeData.enabled !== false && nodeData.drawingEnabled !== false;
        contentParts.right = `
            <label class="gate-switch">
                <input type="checkbox" id="toggle-${nodeData.id}" ${isChecked ? 'checked' : ''} 
                       onchange="window.nodeAction('${nodeData.id}', '${action}', this.checked)">
                <span class="gate-slider"></span>
            </label>
        `;
    } else if (uiComponent === 'rate-display') {
        // Rate display on the right (like RateProbeNode)
        const format = uiConfig.format || '{value}';
        contentParts.right = `<div class="rate-display" id="rate-${nodeData.id}">0/s</div>`;
    }
    
    // Combine parts based on input/output configuration
    if (inputCount === 0 && outputCount > 0) {
        // Input node - button/icon on left
        return `<div class="node-content">${contentParts.left}${contentParts.center}${contentParts.right}</div>`;
    } else if (inputCount > 0 && outputCount === 0) {
        // Output node - title first, then icon, then controls
        return `<div class="node-content">${contentParts.center}${contentParts.right}</div>`;
    } else {
        // Processing node - standard layout
        return `<div class="node-content">${contentParts.left}${contentParts.center}${contentParts.right}</div>`;
    }
}

function attachNodeEventHandlers(nodeEl, nodeData) {
    let isDragging = false;
    let startX, startY;
    let hasMoved = false;
    let isUnconnectedNode = false;
    let snapAnchorPortOffset = null;
    
    nodeEl.addEventListener('mousedown', (e) => {
        if (e.target.classList.contains('port')) return;
        
        // Bring node to front
        nodeEl.style.zIndex = nodeZIndex++;
        
        isDragging = true;
        hasMoved = false;
        startX = e.clientX - nodeData.x;
        startY = e.clientY - nodeData.y;

        // Cache the offset from node top-left to input port 0 center (in canvas/container coords).
        // This lets us snap without forcing repeated DOM reads for the port each frame.
        const portCenter = getInputPort0CenterInCanvasCoords(nodeEl);
        if (portCenter) {
            snapAnchorPortOffset = {
                x: portCenter.x - nodeData.x,
                y: portCenter.y - nodeData.y
            };
        } else {
            snapAnchorPortOffset = null;
        }
        
        // Check if this node has no connections (for hover-insert highlighting)
        isUnconnectedNode = !nodeHasConnections(nodeData.id);
        
        if (e.ctrlKey || e.metaKey) {
            selectNode(nodeData.id, true);
        } else if (!state.selectedNodes.has(nodeData.id)) {
            selectNode(nodeData.id, false);
        }
        
        e.preventDefault();
    });
    
    // Double-click to open properties
    nodeEl.addEventListener('dblclick', (e) => {
        if (e.target.classList.contains('port')) return;
        if (e.target.classList.contains('inject-btn')) return;
        
        // Select the node if not already selected
        if (!state.selectedNodes.has(nodeData.id)) {
            selectNode(nodeData.id, false);
        }
        
        // Show properties panel and render properties
        import('./properties.js').then(({ renderProperties }) => {
            renderProperties(nodeData);
        });
        
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        
        if (!hasMoved) {
            // Save state when movement starts
            hasMoved = true;
            import('./history.js').then(({ saveState }) => {
                saveState('move node');
            });
        }
        
        // Desired anchor node position from pointer
        let nextAnchorX = e.clientX - startX;
        let nextAnchorY = e.clientY - startY;

        // Snap so the anchor input port 0 center lands on the nearest grid intersection.
        if (snapAnchorPortOffset) {
            const desiredPortX = nextAnchorX + snapAnchorPortOffset.x;
            const desiredPortY = nextAnchorY + snapAnchorPortOffset.y;
            const snappedPortX = Math.round(desiredPortX / GRID_SIZE) * GRID_SIZE;
            const snappedPortY = Math.round(desiredPortY / GRID_SIZE) * GRID_SIZE;
            nextAnchorX = snappedPortX - snapAnchorPortOffset.x;
            nextAnchorY = snappedPortY - snapAnchorPortOffset.y;
        } else {
            // Fallback: no input port 0, snap the node top-left.
            nextAnchorX = Math.round(nextAnchorX / GRID_SIZE) * GRID_SIZE;
            nextAnchorY = Math.round(nextAnchorY / GRID_SIZE) * GRID_SIZE;
        }

        const clampedAnchor = clampToCanvasBounds(nextAnchorX, nextAnchorY);
        nextAnchorX = clampedAnchor.x;
        nextAnchorY = clampedAnchor.y;

        const deltaX = nextAnchorX - nodeData.x;
        const deltaY = nextAnchorY - nodeData.y;
        
        state.selectedNodes.forEach(selectedId => {
            const selectedNodeData = state.nodes.get(selectedId);
            const selectedNodeEl = document.getElementById(`node-${selectedId}`);
            if (selectedNodeData && selectedNodeEl) {
                const next = clampToCanvasBounds(selectedNodeData.x + deltaX, selectedNodeData.y + deltaY);
                selectedNodeData.x = next.x;
                selectedNodeData.y = next.y;
                selectedNodeEl.style.left = `${selectedNodeData.x}px`;
                selectedNodeEl.style.top = `${selectedNodeData.y}px`;
            }
        });

        nodeData.x = nextAnchorX;
        nodeData.y = nextAnchorY;
        
        updateConnections();
        
        // Check for connection hover if this is an unconnected node
        // Must happen after updateConnections() to ensure highlight persists
        if (isUnconnectedNode && state.selectedNodes.size === 1) {
            // Get node center position in canvas coordinates
            const nodeRect = nodeEl.getBoundingClientRect();
            const canvasRect = document.getElementById('canvas').getBoundingClientRect();
            const nodeCenterX = nodeRect.left + nodeRect.width / 2 - canvasRect.left;
            const nodeCenterY = nodeRect.top + nodeRect.height / 2 - canvasRect.top;
            
            const hoveredConnection = getConnectionAtPoint(nodeCenterX, nodeCenterY);
            if (hoveredConnection) {
                highlightConnectionForInsert(hoveredConnection);
            } else {
                clearConnectionHighlight();
            }
        }
    });
    
    document.addEventListener('mouseup', () => {
        if (isDragging) {
            // Check if we should insert this node into a connection
            const connectionToInsertInto = getHoveredConnection();
            
            // Clear any connection highlight when drag ends
            clearConnectionHighlight();
            
            // If this was an unconnected node dropped on a connection, insert it
            if (isUnconnectedNode && connectionToInsertInto) {
                insertNodeIntoConnection(nodeData.id, connectionToInsertInto);
            }

            // Snap the moved selection so anchor input port 0 aligns to the grid.
            if (hasMoved) {
                snapSelectedNodesToGrid(nodeData.id);
            }
        }
        isDragging = false;
        hasMoved = false;
        isUnconnectedNode = false;
        snapAnchorPortOffset = null;
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
    
    // Add mouseup handlers on input ports for connection targeting
    const inputPorts = nodeEl.querySelectorAll('.port.input');
    inputPorts.forEach(inputPort => {
        inputPort.addEventListener('mouseup', (e) => {
            if (state.drawingConnection && state.drawingConnection.sourceId !== nodeData.id) {
                e.stopPropagation();
                const inputIndex = parseInt(inputPort.getAttribute('data-index') || '0');
                import('./connections.js').then(({ endConnection }) => {
                    endConnection(nodeData.id, inputIndex);
                });
            }
        });
    });
    
    // Also keep the node-level handler for dropping on the node body (defaults to input 0)
    nodeEl.addEventListener('mouseup', (e) => {
        if (state.drawingConnection && state.drawingConnection.sourceId !== nodeData.id) {
            // Only handle if not already handled by an input port
            if (!e.target.classList.contains('port')) {
                e.stopPropagation();
                import('./connections.js').then(({ endConnection }) => {
                    endConnection(nodeData.id, 0);
                });
            }
        }
    });
}

export function deleteNode(nodeId) {
    // Track deleted connections for incremental deploy
    import('./state.js').then(({ markConnectionDeleted }) => {
        state.connections.forEach(c => {
            if (c.source === nodeId || c.target === nodeId) {
                markConnectionDeleted(c);
            }
        });
    });
    
    state.nodes.delete(nodeId);
    state.connections = state.connections.filter(
        c => c.source !== nodeId && c.target !== nodeId
    );
    
    document.getElementById(`node-${nodeId}`)?.remove();
    updateConnections();
    
    if (state.selectedNode === nodeId) {
        import('./selection.js').then(({ deselectNode }) => deselectNode());
    }
    
    // Track deleted node for incremental deploy
    markNodeDeleted(nodeId);
    setModified(true);
}

// Delete a node but reconnect the nodes on either side
export function deleteNodeAndReconnect(nodeId) {
    const nodeData = state.nodes.get(nodeId);
    if (!nodeData) return;
    
    // Find all incoming connections (where this node is the target)
    const incomingConnections = state.connections.filter(c => c.target === nodeId);
    
    // Find all outgoing connections (where this node is the source)
    const outgoingConnections = state.connections.filter(c => c.source === nodeId);
    
    // Import createConnection to make the new connections
    import('./connections.js').then(({ createConnection }) => {
        // Connect each incoming source to each outgoing target
        incomingConnections.forEach(incoming => {
            outgoingConnections.forEach(outgoing => {
                // Check if connection already exists
                const exists = state.connections.some(c => 
                    c.source === incoming.source && 
                    c.target === outgoing.target &&
                    c.sourceOutput === incoming.sourceOutput
                );
                
                if (!exists) {
                    createConnection(
                        incoming.source,
                        outgoing.target,
                        incoming.sourceOutput,
                        outgoing.targetInput || 0
                    );
                }
            });
        });
        
        // Now delete the node (which removes its connections)
        deleteNode(nodeId);
    });
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

export function updateNodeInputCount(nodeId, inputCount) {
    const nodeData = state.nodes.get(nodeId);
    if (!nodeData) return;
    
    // Update the input count
    nodeData.inputCount = inputCount;
    
    // Re-render the node
    const nodeEl = document.getElementById(`node-${nodeId}`);
    if (nodeEl) {
        nodeEl.remove();
        renderNode(nodeData);
        updateConnections();
    }
}

// Unified node action handler
window.nodeAction = async function(nodeId, action, value) {
    try {
        // Handle different action types
        if (action === 'inject') {
            await fetch(`${API_BASE}/nodes/${nodeId}/inject`, { method: 'POST' });
        } else if (action === 'toggle_gate') {
            await window.toggleGate(nodeId, value);
        } else if (action === 'toggle_debug') {
            await window.toggleDebug(nodeId, value);
        } else if (action === 'toggle_drawing') {
            await window.toggleDrawPredictions(nodeId, value);
        } else {
            // Generic action - call the action endpoint
            await fetch(`${API_BASE}/nodes/${nodeId}/${action}`, { method: 'POST' });
        }
    } catch (error) {
        console.error(`Failed to execute action ${action} on node ${nodeId}:`, error);
    }
};

// Toggle draw predictions enabled state
window.toggleDrawPredictions = async function(nodeId, enabled) {
    try {
        // Call the toggle_drawing action on the backend
        const response = await fetch(`${API_BASE}/nodes/${nodeId}/toggle_drawing`, {
            method: 'POST'
        });
        
        if (response.ok) {
            const nodeData = state.nodes.get(nodeId);
            if (nodeData) {
                // Store the state in nodeData for persistence
                nodeData.drawingEnabled = enabled;
            }
            
            console.log(`Draw predictions ${enabled ? 'enabled' : 'disabled'} for node ${nodeId}`);
        }
    } catch (error) {
        console.error('Failed to toggle draw predictions:', error);
    }
};

// Toggle debug node enabled state - delegates to toggleNodeState
window.toggleDebug = async function(nodeId, enabled) {
    // Use the consolidated toggleNodeState from properties.js
    await window.toggleNodeState(nodeId, enabled);
};

// Trigger inject node
window.triggerInject = async function(nodeId) {
    try {
        await fetch(`${API_BASE}/nodes/${nodeId}/inject`, { method: 'POST' });
    } catch (error) {
        console.error('Failed to trigger inject:', error);
    }
};
