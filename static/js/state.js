// State management module
export const state = {
    nodes: new Map(),
    connections: [],
    selectedNode: null,
    selectedNodes: new Set(),
    selectedConnection: null,
    draggingNode: null,
    drawingConnection: null,
    nodeTypes: [],
    selectionBox: null,
    selectionStart: null,
    isModified: false,
    nextNodeId: 1,
    // Track changes for incremental deployment
    modifiedNodes: new Set(),
    addedNodes: new Set(),
    deletedNodes: new Set(),
    addedConnections: [],
    deletedConnections: []
};

// Generate a client-side node ID
export function generateNodeId() {
    return `node_${Date.now()}_${state.nextNodeId++}`;
}

// Set modified state and update deploy button
export function setModified(modified) {
    state.isModified = modified;
    const deployBtn = document.getElementById('deploy-btn');
    if (deployBtn) {
        deployBtn.disabled = !modified;
    }
}

// Mark a node as modified
export function markNodeModified(nodeId) {
    const nodeEl = document.getElementById(`node-${nodeId}`);
    if (nodeEl) {
        nodeEl.classList.add('modified');
    }
    // Track modified node for incremental deploy
    if (!state.addedNodes.has(nodeId)) {
        state.modifiedNodes.add(nodeId);
    }
}

// Mark a node as newly added
export function markNodeAdded(nodeId) {
    state.addedNodes.add(nodeId);
}

// Mark a node as deleted
export function markNodeDeleted(nodeId) {
    // If it was added in this session, just remove from added
    if (state.addedNodes.has(nodeId)) {
        state.addedNodes.delete(nodeId);
    } else {
        state.deletedNodes.add(nodeId);
    }
    state.modifiedNodes.delete(nodeId);
}

// Track added connection
export function markConnectionAdded(connection) {
    state.addedConnections.push({...connection});
}

// Track deleted connection
export function markConnectionDeleted(connection) {
    // Check if it was added in this session
    const addedIdx = state.addedConnections.findIndex(c => 
        c.source === connection.source && 
        c.target === connection.target &&
        c.sourceOutput === connection.sourceOutput
    );
    if (addedIdx >= 0) {
        state.addedConnections.splice(addedIdx, 1);
    } else {
        state.deletedConnections.push({...connection});
    }
}

// Clear all change tracking after deploy
export function clearChangeTracking() {
    state.modifiedNodes.clear();
    state.addedNodes.clear();
    state.deletedNodes.clear();
    state.addedConnections = [];
    state.deletedConnections = [];
}

// Check if there are any changes to deploy
export function hasChanges() {
    return state.modifiedNodes.size > 0 || 
           state.addedNodes.size > 0 || 
           state.deletedNodes.size > 0 ||
           state.addedConnections.length > 0 ||
           state.deletedConnections.length > 0;
}

// Clear all node modified indicators
export function clearAllNodeModifiedIndicators() {
    document.querySelectorAll('.node.modified').forEach(nodeEl => {
        nodeEl.classList.remove('modified');
    });
}
