// State management module
export const state = {
    nodes: new Map(),
    connections: [],
    selectedNode: null,
    selectedNodes: new Set(),
    draggingNode: null,
    drawingConnection: null,
    nodeTypes: [],
    selectionBox: null,
    selectionStart: null,
    isModified: false,
    nextNodeId: 1
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
}

// Clear all node modified indicators
export function clearAllNodeModifiedIndicators() {
    document.querySelectorAll('.node.modified').forEach(nodeEl => {
        nodeEl.classList.remove('modified');
    });
}
