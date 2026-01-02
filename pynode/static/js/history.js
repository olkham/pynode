// Undo/Redo history management
import { state, setModified } from './state.js';
import { renderNode, deleteNode } from './nodes.js';
import { createConnection, deleteConnection, updateConnections } from './connections.js';
import { deselectAllNodes } from './selection.js';

// History state
const history = {
    undoStack: [],
    redoStack: [],
    maxStackSize: 50,
    isApplyingHistory: false
};

/**
 * Save current state to undo stack
 */
export function saveState(action = 'change') {
    // Don't save state if we're applying history
    if (history.isApplyingHistory) return;
    
    // Create a snapshot of current state
    const snapshot = {
        action: action,
        timestamp: Date.now(),
        nodes: new Map(),
        connections: [],
        selectedNodes: new Set(state.selectedNodes)
    };
    
    // Deep copy nodes
    state.nodes.forEach((node, id) => {
        snapshot.nodes.set(id, { ...node });
    });
    
    // Deep copy connections
    snapshot.connections = state.connections.map(conn => ({ ...conn }));
    
    // Add to undo stack
    history.undoStack.push(snapshot);
    
    // Limit stack size
    if (history.undoStack.length > history.maxStackSize) {
        history.undoStack.shift();
    }
    
    // Clear redo stack when new action is performed
    history.redoStack = [];
    
    console.log(`State saved (${action}). Undo stack: ${history.undoStack.length}, Redo stack: ${history.redoStack.length}`);
}

/**
 * Undo last action
 */
export function undo() {
    if (history.undoStack.length === 0) {
        console.log('Nothing to undo');
        return;
    }
    
    // Save current state to redo stack
    const currentSnapshot = {
        action: 'current',
        timestamp: Date.now(),
        nodes: new Map(),
        connections: [],
        selectedNodes: new Set(state.selectedNodes)
    };
    
    state.nodes.forEach((node, id) => {
        currentSnapshot.nodes.set(id, { ...node });
    });
    currentSnapshot.connections = state.connections.map(conn => ({ ...conn }));
    
    history.redoStack.push(currentSnapshot);
    
    // Get previous state
    const snapshot = history.undoStack.pop();
    
    // Apply the snapshot
    applySnapshot(snapshot);
    
    console.log(`Undid action: ${snapshot.action}. Undo stack: ${history.undoStack.length}, Redo stack: ${history.redoStack.length}`);
}

/**
 * Redo last undone action
 */
export function redo() {
    if (history.redoStack.length === 0) {
        console.log('Nothing to redo');
        return;
    }
    
    // Save current state to undo stack
    const currentSnapshot = {
        action: 'before redo',
        timestamp: Date.now(),
        nodes: new Map(),
        connections: [],
        selectedNodes: new Set(state.selectedNodes)
    };
    
    state.nodes.forEach((node, id) => {
        currentSnapshot.nodes.set(id, { ...node });
    });
    currentSnapshot.connections = state.connections.map(conn => ({ ...conn }));
    
    history.undoStack.push(currentSnapshot);
    
    // Get next state
    const snapshot = history.redoStack.pop();
    
    // Apply the snapshot
    applySnapshot(snapshot);
    
    console.log(`Redid action. Undo stack: ${history.undoStack.length}, Redo stack: ${history.redoStack.length}`);
}

/**
 * Apply a snapshot to current state
 */
function applySnapshot(snapshot) {
    history.isApplyingHistory = true;
    
    try {
        // Clear current selection
        deselectAllNodes();
        
        // Remove all existing nodes from DOM
        state.nodes.forEach((node, id) => {
            const nodeEl = document.getElementById(`node-${id}`);
            if (nodeEl) nodeEl.remove();
        });
        
        // Clear state
        state.nodes.clear();
        state.connections = [];
        
        // Restore nodes
        snapshot.nodes.forEach((node, id) => {
            state.nodes.set(id, { ...node });
            renderNode(node);
        });
        
        // Restore connections
        snapshot.connections.forEach(conn => {
            state.connections.push({ ...conn });
        });
        
        updateConnections();
        
        // Restore selection (optional)
        // snapshot.selectedNodes.forEach(nodeId => {
        //     if (state.nodes.has(nodeId)) {
        //         selectNode(nodeId, true);
        //     }
        // });
        
        setModified(true);
    } finally {
        history.isApplyingHistory = false;
    }
}

/**
 * Check if undo is available
 */
export function canUndo() {
    return history.undoStack.length > 0;
}

/**
 * Check if redo is available
 */
export function canRedo() {
    return history.redoStack.length > 0;
}

/**
 * Clear history
 */
export function clearHistory() {
    history.undoStack = [];
    history.redoStack = [];
    console.log('History cleared');
}

/**
 * Get current history state info (for debugging)
 */
export function getHistoryInfo() {
    return {
        undoStackSize: history.undoStack.length,
        redoStackSize: history.redoStack.length,
        isApplyingHistory: history.isApplyingHistory
    };
}
