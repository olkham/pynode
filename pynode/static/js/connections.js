// Connection management
import { state, markNodeModified, markConnectionAdded, markConnectionDeleted, setModified } from './state.js';

// Track the currently hovered connection for insertion
let hoveredConnectionForInsert = null;

// Check if a node has any connections
export function nodeHasConnections(nodeId) {
    return state.connections.some(c => c.source === nodeId || c.target === nodeId);
}

// Get the currently hovered connection (for insertion)
export function getHoveredConnection() {
    return hoveredConnectionForInsert;
}

// Check if a point is near a connection path and return the connection if so
export function getConnectionAtPoint(x, y, threshold = 15) {
    const paths = document.querySelectorAll('#connections path.connection');
    let closestConnection = null;
    let closestDistance = Infinity;
    
    console.log(`Checking connections at (${x.toFixed(1)}, ${y.toFixed(1)}) with threshold ${threshold}px`);
    
    for (const path of paths) {
        // Calculate actual distance to the path by sampling points along it
        const pathLength = path.getTotalLength();
        const step = 10; // Sample every 10px for accuracy
        let minDistanceForPath = Infinity;
        
        for (let i = 0; i <= pathLength; i += step) {
            const point = path.getPointAtLength(i);
            const dx = point.x - x;
            const dy = point.y - y;
            const distance = Math.sqrt(dx * dx + dy * dy);
            
            if (distance < minDistanceForPath) {
                minDistanceForPath = distance;
            }
            
            if (distance < closestDistance) {
                closestDistance = distance;
                closestConnection = {
                    source: path.getAttribute('data-source'),
                    target: path.getAttribute('data-target'),
                    sourceOutput: parseInt(path.getAttribute('data-source-output') || '0'),
                    path: path
                };
            }
        }
        
        console.log(`  Path ${path.getAttribute('data-source')} -> ${path.getAttribute('data-target')}: min distance = ${minDistanceForPath.toFixed(1)}px`);
    }
    
    if (closestConnection && closestDistance <= threshold) {
        console.log(`  → Selected connection at ${closestDistance.toFixed(1)}px distance`);
        return closestConnection;
    }
    
    console.log(`  → No connection within threshold`);
    return null;
}

// Highlight a connection with dashed style (for hover-insert indication)
export function highlightConnectionForInsert(connection) {
    clearConnectionHighlight();
    
    if (!connection) return;
    
    // Track the hovered connection
    hoveredConnectionForInsert = connection;
    
    const paths = document.querySelectorAll('#connections path.connection');
    paths.forEach(path => {
        if (path.getAttribute('data-source') === connection.source &&
            path.getAttribute('data-target') === connection.target &&
            parseInt(path.getAttribute('data-source-output') || '0') === connection.sourceOutput) {
            path.classList.add('hover-insert');
        }
    });
}

// Clear connection highlight
export function clearConnectionHighlight() {
    hoveredConnectionForInsert = null;
    const paths = document.querySelectorAll('#connections path.connection.hover-insert');
    paths.forEach(path => path.classList.remove('hover-insert'));
}

// Insert a node into an existing connection (split the connection)
export function insertNodeIntoConnection(nodeId, connection) {
    if (!connection) return false;
    
    const nodeData = state.nodes.get(nodeId);
    if (!nodeData) return false;
    
    // Check if node has both input and output ports
    const inputCount = nodeData.inputCount !== undefined ? nodeData.inputCount : 1;
    const outputCount = nodeData.outputCount !== undefined ? nodeData.outputCount : 1;
    
    if (inputCount === 0 || outputCount === 0) {
        // Can't insert a node without both input and output
        return false;
    }
    
    // Save state for undo
    import('./history.js').then(({ saveState }) => {
        saveState('insert node into connection');
    });
    
    // Delete the original connection
    deleteConnection(connection.source, connection.target, connection.sourceOutput);
    
    // Create connection from original source to the new node
    createConnection(connection.source, nodeId, connection.sourceOutput, 0);
    
    // Create connection from the new node to the original target
    createConnection(nodeId, connection.target, 0, 0);
    
    return true;
}

export function createConnection(sourceId, targetId, sourceOutput = 0, targetInput = 0) {
    const connection = {
        source: sourceId,
        target: targetId,
        sourceOutput: sourceOutput,
        targetInput: targetInput
    };
    
    state.connections.push(connection);
    renderConnection(connection);
    markConnectionAdded(connection);
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
    
    // Get the correct input port based on index
    const inputPorts = targetEl.querySelectorAll('.port.input');
    const targetPort = inputPorts[connection.targetInput || 0] || targetEl.querySelector('.port.input');
    
    if (!sourcePort || !targetPort) return;
    
    const sourceRect = sourcePort.getBoundingClientRect();
    const targetRect = targetPort.getBoundingClientRect();
    const canvasRect = document.getElementById('canvas').getBoundingClientRect();
    
    const x1 = sourceRect.left + sourceRect.width / 2 - canvasRect.left;
    const y1 = sourceRect.top + sourceRect.height / 2 - canvasRect.top;
    const x2 = targetRect.left + targetRect.width / 2 - canvasRect.left;
    const y2 = targetRect.top + targetRect.height / 2 - canvasRect.top;
    
    // Arrowhead always ends at the target port
    // For near-vertical connections, adjust control points for a visible curve
    // Arrowhead is always at the target port (x2, y2)
    // Control points are adjusted for a smooth curve, but never move the end point
    const dx = x2 - x1;
    
    // Gradual transition: minCurve increases as the connection goes backwards
    // Forward (dx > 0): minCurve = 30
    // Backwards (dx < 0): minCurve grows larger as dx becomes more negative
    let minCurve = 30;
    if (dx < 0) {
        // Gradually increase minCurve based on how far back it goes
        // At dx = -100, minCurve ≈ 55; at dx = -200, minCurve ≈ 80
        minCurve = 30 + Math.abs(dx) * 0.5;
        minCurve = Math.min(minCurve, 100); // Cap at 100
    }

    const dy = y2 - y1;
    const distance = Math.sqrt(dx * dx + dy * dy);
    // minCurve = Math.min(minCurve, distance / 2 - 10);

    let control = Math.max(Math.abs(dx) * 0.3, minCurve);
    // let control = 0;
    // Control points: always horizontally offset from source/target
    const cx1 = x1 + control;
    const cx2 = x2 - control;
    const pathData = `M ${x1} ${y1} C ${cx1} ${y1}, ${cx2} ${y2}, ${x2} ${y2}`;
    
    // Create visible path (no arrowhead)
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('class', 'connection');
    path.setAttribute('d', pathData);
    // No marker-end (arrowhead)
    path.setAttribute('data-source', connection.source);
    path.setAttribute('data-target', connection.target);
    path.setAttribute('data-source-output', connection.sourceOutput || 0);
    path.setAttribute('data-target-input', connection.targetInput || 0);
    path.style.pointerEvents = 'none';
    
    // Add disabled class if either node is disabled
    if (sourceNode.enabled === false || targetNode.enabled === false) {
        path.classList.add('disabled');
    }
    
    // Check if this connection is selected
    if (state.selectedConnection && 
        state.selectedConnection.source === connection.source &&
        state.selectedConnection.target === connection.target &&
        state.selectedConnection.sourceOutput === (connection.sourceOutput || 0)) {
        path.classList.add('selected');
        console.log('Added selected class to connection:', connection.source, '->', connection.target);
    }
    
    // Check if this connection is selected
    if (state.selectedConnection && 
        state.selectedConnection.source === connection.source &&
        state.selectedConnection.target === connection.target &&
        state.selectedConnection.sourceOutput === (connection.sourceOutput || 0)) {
        path.classList.add('selected');
    }
    
    // Append visible path
    document.getElementById('connections').appendChild(path);
}

export function updateConnections() {
    const connectionsSvg = document.getElementById('connections');
    // Ensure marker is present only once
    let defs = connectionsSvg.querySelector('defs');
    if (!defs) {
        defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
        // marker.setAttribute('id', 'arrowhead');
        marker.setAttribute('markerWidth', '10');
        marker.setAttribute('markerHeight', '7');
        marker.setAttribute('refX', '10');
        marker.setAttribute('refY', '3.5');
        marker.setAttribute('orient', 'auto');
        marker.setAttribute('markerUnits', 'strokeWidth');
        // const arrowPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        // arrowPath.setAttribute('d', 'M0,0 L10,3.5 L0,7 Z');
        // arrowPath.setAttribute('fill', '#0e639c');
        // marker.appendChild(arrowPath);
        defs.appendChild(marker);
        connectionsSvg.insertBefore(defs, connectionsSvg.firstChild);
    }
    // Remove only connection paths, not defs/marker
    Array.from(connectionsSvg.querySelectorAll('path.connection, path[stroke="transparent"]')).forEach(el => el.remove());
    state.connections.forEach(conn => renderConnection(conn));
}

export function deleteConnection(sourceId, targetId, sourceOutput = null) {
    // Track deleted connections for incremental deploy
    state.connections.forEach(c => {
        if (c.source === sourceId && c.target === targetId && 
            (sourceOutput === null || c.sourceOutput === sourceOutput)) {
            markConnectionDeleted(c);
        }
    });
    
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

// Start a backward connection (dragging from input port)
export function startBackwardConnection(targetId, e, inputIndex = 0) {
    const targetNode = document.getElementById(`node-${targetId}`);
    const inputPorts = targetNode.querySelectorAll('.port.input');
    const port = inputPorts[inputIndex] || targetNode.querySelector('.port.input');
    
    if (!port) return;
    
    const rect = port.getBoundingClientRect();
    const canvasRect = document.getElementById('canvas').getBoundingClientRect();
    
    state.drawingConnection = {
        targetId: targetId,
        inputIndex: inputIndex,
        startX: rect.left + rect.width / 2 - canvasRect.left,
        startY: rect.top + rect.height / 2 - canvasRect.top,
        backward: true  // Flag to indicate backward connection
    };
    
    document.addEventListener('mousemove', drawTempConnection);
    document.addEventListener('mouseup', cancelConnection);
}

export function drawTempConnection(e) {
    if (!state.drawingConnection) return;
    
    const canvasRect = document.getElementById('canvas').getBoundingClientRect();
    const endX = e.clientX - canvasRect.left;
    const endY = e.clientY - canvasRect.top;
    
    const dx = endX - state.drawingConnection.startX;
    const controlDistance = Math.abs(dx) * 0.5;
    
    const tempLine = document.getElementById('temp-line');
    
    if (state.drawingConnection.backward) {
        // Backward connection: input port is on the left, so curve goes left first
        tempLine.innerHTML = `
            <path d="M ${state.drawingConnection.startX} ${state.drawingConnection.startY} 
                     C ${state.drawingConnection.startX - controlDistance} ${state.drawingConnection.startY},
                         ${endX + controlDistance} ${endY},
                         ${endX} ${endY}"
                  stroke="#0e639c" stroke-width="2" fill="none" />
        `;
    } else {
        // Forward connection: output port is on the right, so curve goes right first
        tempLine.innerHTML = `
            <path d="M ${state.drawingConnection.startX} ${state.drawingConnection.startY} 
                     C ${state.drawingConnection.startX + controlDistance} ${state.drawingConnection.startY},
                         ${endX - controlDistance} ${endY},
                         ${endX} ${endY}"
                  stroke="#0e639c" stroke-width="2" fill="none" />
        `;
    }
}

export function endConnection(targetId, targetInputIndex = 0) {
    if (!state.drawingConnection) return;
    
    const sourceId = state.drawingConnection.sourceId;
    const outputIndex = state.drawingConnection.outputIndex || 0;
    
    if (sourceId !== targetId) {
        // Save state before creating connection
        import('./history.js').then(({ saveState }) => {
            saveState('create connection');
        });
        createConnection(sourceId, targetId, outputIndex, targetInputIndex);
    }
    
    cancelConnection();
}

// End a backward connection (dropped on output port)
export function endBackwardConnection(sourceId, outputIndex = 0) {
    if (!state.drawingConnection || !state.drawingConnection.backward) return;
    
    const targetId = state.drawingConnection.targetId;
    const inputIndex = state.drawingConnection.inputIndex || 0;
    
    if (sourceId !== targetId) {
        // Save state before creating connection
        import('./history.js').then(({ saveState }) => {
            saveState('create connection');
        });
        // Connection is source -> target (backward was just UI direction)
        createConnection(sourceId, targetId, outputIndex, inputIndex);
    }
    
    cancelConnection();
}

export function cancelConnection(e) {
    const hadConnection = state.drawingConnection !== null;
    const isBackward = state.drawingConnection?.backward;
    const mousePos = e ? { x: e.clientX, y: e.clientY } : null;
    
    if (hadConnection && mousePos) {
        // Draw the temp line to the final position before showing mini palette
        const canvasRect = document.getElementById('canvas').getBoundingClientRect();
        const endX = mousePos.x - canvasRect.left;
        const endY = mousePos.y - canvasRect.top;
        const dx = endX - state.drawingConnection.startX;
        const controlDistance = Math.abs(dx) * 0.5;
        
        const tempLine = document.getElementById('temp-line');
        
        if (isBackward) {
            // Backward connection: curve goes left first from input port
            tempLine.innerHTML = `
                <path d="M ${state.drawingConnection.startX} ${state.drawingConnection.startY} 
                         C ${state.drawingConnection.startX - controlDistance} ${state.drawingConnection.startY},
                             ${endX + controlDistance} ${endY},
                             ${endX} ${endY}"
                      stroke="#0e639c" stroke-width="2" fill="none" />
            `;
        } else {
            // Forward connection: curve goes right first from output port
            tempLine.innerHTML = `
                <path d="M ${state.drawingConnection.startX} ${state.drawingConnection.startY} 
                         C ${state.drawingConnection.startX + controlDistance} ${state.drawingConnection.startY},
                             ${endX - controlDistance} ${endY},
                             ${endX} ${endY}"
                      stroke="#0e639c" stroke-width="2" fill="none" />
            `;
        }
        
        // Show mini palette at mouse position (temp line will be cleared when palette closes)
        if (isBackward) {
            // Backward connection: show palette to create node that outputs TO this input
            showMiniPaletteBackward(mousePos.x, mousePos.y, state.drawingConnection.targetId, state.drawingConnection.inputIndex);
        } else {
            // Forward connection: show palette to create node that receives FROM this output
            showMiniPalette(mousePos.x, mousePos.y, state.drawingConnection.sourceId, state.drawingConnection.outputIndex);
        }
    } else {
        // No mini palette, clear the temp line immediately
        document.getElementById('temp-line').innerHTML = '';
    }
    
    state.drawingConnection = null;
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

function showMiniPalette(x, y, sourceId, outputIndex) {
    // Remove existing mini palette if any
    const existing = document.getElementById('mini-palette');
    if (existing) existing.remove();
    
    // Create mini palette
    const miniPalette = document.createElement('div');
    miniPalette.id = 'mini-palette';
    miniPalette.className = 'mini-palette';
    miniPalette.style.left = `${x}px`;
    miniPalette.style.top = `${y}px`;
    
    // Add search field
    const searchContainer = document.createElement('div');
    searchContainer.className = 'mini-palette-search-container';
    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.className = 'mini-palette-search';
    searchInput.placeholder = 'Filter nodes...';
    searchInput.addEventListener('click', (e) => e.stopPropagation());
    searchInput.addEventListener('input', (e) => {
        const filter = e.target.value.toLowerCase().trim();
        filterMiniPaletteNodes(miniPalette, filter);
    });
    searchContainer.appendChild(searchInput);
    miniPalette.appendChild(searchContainer);
    
    // Create content container for categories
    const contentContainer = document.createElement('div');
    contentContainer.className = 'mini-palette-content';
    
    // Only show nodes that have inputs (filter out source-only nodes like Inject)
    // Dynamically group nodes by category, preserving order of first appearance
    const categories = {};
    const categoryOrder = [];
    
    state.nodeTypes.forEach(nodeType => {
        // Only show nodes that have at least one input
        if (nodeType.inputCount === 0) return;
        
        const category = nodeType.category || 'custom';
        if (!categories[category]) {
            categories[category] = {
                title: category.charAt(0).toUpperCase() + category.slice(1),
                nodes: []
            };
            categoryOrder.push(category);
        }
        categories[category].nodes.push(nodeType);
    });
    
    // Create palette items in category order
    categoryOrder.forEach(category => {
        const categoryData = categories[category];
        if (!categoryData || categoryData.nodes.length === 0) return;
        
        const categoryDiv = document.createElement('div');
        categoryDiv.className = 'mini-palette-category';
        
        const categoryLabel = document.createElement('div');
        categoryLabel.className = 'mini-palette-category-label';
        categoryLabel.textContent = categoryData.title;
        categoryDiv.appendChild(categoryLabel);
        
        categoryData.nodes.forEach(nodeType => {
            const item = document.createElement('div');
            item.className = 'mini-palette-item';
            item.innerHTML = `<span class="mini-palette-icon">${nodeType.icon}</span><span class="mini-palette-item-name">${nodeType.name}</span>`;
            if (nodeType.color) item.style.backgroundColor = nodeType.color;
            if (nodeType.borderColor) item.style.borderColor = nodeType.borderColor;
            if (nodeType.textColor) item.style.color = nodeType.textColor;
            
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                createNodeAndConnect(nodeType.type, x, y, sourceId, outputIndex);
                closeMiniPalette();
            });
            
            categoryDiv.appendChild(item);
        });
        
        contentContainer.appendChild(categoryDiv);
    });
    
    miniPalette.appendChild(contentContainer);
    document.body.appendChild(miniPalette);
    
    // Focus the search input
    setTimeout(() => {
        searchInput.focus();
    }, 0);
    
    // Close on click outside
    setTimeout(() => {
        document.addEventListener('click', closeMiniPalette, { once: true });
        document.addEventListener('keydown', handleMiniPaletteKeydown);
    }, 0);
}

function filterMiniPaletteNodes(palette, filter) {
    const categories = palette.querySelectorAll('.mini-palette-category');
    
    categories.forEach(category => {
        const items = category.querySelectorAll('.mini-palette-item');
        let visibleCount = 0;
        
        items.forEach(item => {
            const itemName = item.querySelector('.mini-palette-item-name').textContent.toLowerCase();
            if (!filter || itemName.includes(filter)) {
                item.style.display = '';
                visibleCount++;
            } else {
                item.style.display = 'none';
            }
        });
        
        // Hide category if no items match
        category.style.display = visibleCount > 0 ? '' : 'none';
    });
}

function closeMiniPalette() {
    const miniPalette = document.getElementById('mini-palette');
    if (miniPalette) {
        miniPalette.remove();
    }
    // Clear the temp connection line
    document.getElementById('temp-line').innerHTML = '';
    document.removeEventListener('keydown', handleMiniPaletteKeydown);
}

function handleMiniPaletteKeydown(e) {
    if (e.key === 'Escape') {
        closeMiniPalette();
    }
}

function createNodeAndConnect(nodeType, x, y, sourceId, outputIndex, targetInputIndex = 0) {
    import('./nodes.js').then(({ createNode, snapNodeToGrid }) => {
        // Convert screen coordinates to canvas coordinates
        // Use nodes-container rect (same as handleCanvasDrop in events.js)
        const nodesContainer = document.getElementById('nodes-container');
        const containerRect = nodesContainer.getBoundingClientRect();
        const canvasX = x - containerRect.left;
        const canvasY = y - containerRect.top;
        
        // Create the new node
        const newNodeId = createNode(nodeType, canvasX, canvasY);
        
        // Snap to grid and create connection after a brief delay to ensure node is rendered
        setTimeout(() => {
            snapNodeToGrid(newNodeId);
            // Connect based on direction: sourceId->newNode or newNode->sourceId
            if (sourceId && outputIndex !== null) {
                createConnection(sourceId, newNodeId, outputIndex, targetInputIndex);
            }
        }, 50);
    });
}

// Show mini palette for backward connection (dragged from input port)
// Creates a node that will OUTPUT to the target node's input
function showMiniPaletteBackward(x, y, targetId, inputIndex) {
    // Remove existing mini palette if any
    const existing = document.getElementById('mini-palette');
    if (existing) existing.remove();
    
    // Create mini palette
    const miniPalette = document.createElement('div');
    miniPalette.id = 'mini-palette';
    miniPalette.className = 'mini-palette';
    miniPalette.style.left = `${x}px`;
    miniPalette.style.top = `${y}px`;
    
    // Add search field
    const searchContainer = document.createElement('div');
    searchContainer.className = 'mini-palette-search-container';
    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.className = 'mini-palette-search';
    searchInput.placeholder = 'Filter nodes...';
    searchInput.addEventListener('click', (e) => e.stopPropagation());
    searchInput.addEventListener('input', (e) => {
        const filter = e.target.value.toLowerCase().trim();
        filterMiniPaletteNodes(miniPalette, filter);
    });
    searchContainer.appendChild(searchInput);
    miniPalette.appendChild(searchContainer);
    
    // Create content container for categories
    const contentContainer = document.createElement('div');
    contentContainer.className = 'mini-palette-content';
    
    // Show nodes that have outputs (filter out terminal nodes with no outputs)
    // Dynamically group nodes by category, preserving order of first appearance
    const categories = {};
    const categoryOrder = [];
    
    state.nodeTypes.forEach(nodeType => {
        // Only show nodes that have at least one output
        if (nodeType.outputCount === 0) return;
        
        const category = nodeType.category || 'custom';
        if (!categories[category]) {
            categories[category] = {
                title: category.charAt(0).toUpperCase() + category.slice(1),
                nodes: []
            };
            categoryOrder.push(category);
        }
        categories[category].nodes.push(nodeType);
    });
    
    // Create palette items in category order
    categoryOrder.forEach(category => {
        const categoryData = categories[category];
        if (!categoryData || categoryData.nodes.length === 0) return;
        
        const categoryDiv = document.createElement('div');
        categoryDiv.className = 'mini-palette-category';
        
        const categoryLabel = document.createElement('div');
        categoryLabel.className = 'mini-palette-category-label';
        categoryLabel.textContent = categoryData.title;
        categoryDiv.appendChild(categoryLabel);
        
        categoryData.nodes.forEach(nodeType => {
            const item = document.createElement('div');
            item.className = 'mini-palette-item';
            item.innerHTML = `<span class="mini-palette-icon">${nodeType.icon}</span><span class="mini-palette-item-name">${nodeType.name}</span>`;
            if (nodeType.color) item.style.backgroundColor = nodeType.color;
            if (nodeType.borderColor) item.style.borderColor = nodeType.borderColor;
            if (nodeType.textColor) item.style.color = nodeType.textColor;
            
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                // Create node and connect its output (0) to target's input
                createNodeAndConnectBackward(nodeType.type, x, y, targetId, inputIndex);
                closeMiniPalette();
            });
            
            categoryDiv.appendChild(item);
        });
        
        contentContainer.appendChild(categoryDiv);
    });
    
    miniPalette.appendChild(contentContainer);
    document.body.appendChild(miniPalette);
    
    // Focus the search input
    setTimeout(() => {
        searchInput.focus();
    }, 0);
    
    // Close on click outside
    setTimeout(() => {
        document.addEventListener('click', closeMiniPalette, { once: true });
        document.addEventListener('keydown', handleMiniPaletteKeydown);
    }, 0);
}

// Create a node and connect its output to an existing target node's input
function createNodeAndConnectBackward(nodeType, x, y, targetId, targetInputIndex = 0) {
    import('./nodes.js').then(({ createNode, snapNodeToGrid }) => {
        // Convert screen coordinates to canvas coordinates
        const nodesContainer = document.getElementById('nodes-container');
        const containerRect = nodesContainer.getBoundingClientRect();
        const canvasX = x - containerRect.left;
        const canvasY = y - containerRect.top;
        
        // Create the new node
        const newNodeId = createNode(nodeType, canvasX, canvasY);
        
        // Snap to grid and create connection after a brief delay to ensure node is rendered
        setTimeout(() => {
            snapNodeToGrid(newNodeId);
            // Connect newNode's output 0 to targetId's input
            createConnection(newNodeId, targetId, 0, targetInputIndex);
        }, 50);
    });
}
