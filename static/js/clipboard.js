// Clipboard management for copy, cut, paste operations
import { state, generateNodeId, setModified } from './state.js';
import { renderNode } from './nodes.js';
import { createConnection } from './connections.js';
import { selectNode } from './selection.js';

// Clipboard state
const clipboard = {
    nodes: [],
    connections: [],
    isCut: false
};

/**
 * Copy selected nodes to clipboard
 */
export function copySelectedNodes() {
    if (state.selectedNodes.size === 0) {
        console.log('No nodes selected to copy');
        return;
    }
    
    clipboard.nodes = [];
    clipboard.connections = [];
    clipboard.isCut = false;
    
    // Copy node data
    state.selectedNodes.forEach(nodeId => {
        const node = state.nodes.get(nodeId);
        if (node) {
            clipboard.nodes.push({
                ...node,
                originalId: node.id
            });
        }
    });
    
    // Copy connections between selected nodes
    state.connections.forEach(conn => {
        if (state.selectedNodes.has(conn.source) && state.selectedNodes.has(conn.target)) {
            clipboard.connections.push({ ...conn });
        }
    });
    
    console.log(`Copied ${clipboard.nodes.length} nodes and ${clipboard.connections.length} connections`);
}

/**
 * Cut selected nodes to clipboard
 */
export function cutSelectedNodes() {
    if (state.selectedNodes.size === 0) {
        console.log('No nodes selected to cut');
        return;
    }
    
    // First copy the nodes
    copySelectedNodes();
    clipboard.isCut = true;
    
    // Then delete them
    const nodesToDelete = Array.from(state.selectedNodes);
    
    // Import deleteNode dynamically
    import('./nodes.js').then(({ deleteNode }) => {
        nodesToDelete.forEach(nodeId => {
            deleteNode(nodeId);
        });
    });
    
    console.log(`Cut ${clipboard.nodes.length} nodes`);
}

/**
 * Paste nodes from clipboard
 */
export function pasteNodes() {
    if (clipboard.nodes.length === 0) {
        console.log('Clipboard is empty');
        return;
    }
    
    // Clear current selection
    import('./selection.js').then(({ deselectAllNodes }) => {
        deselectAllNodes();
    });
    
    // Map old IDs to new IDs
    const idMap = new Map();
    
    // Calculate paste offset (20px down and right from original position)
    const pasteOffset = clipboard.isCut ? 0 : 20;
    
    // Create new nodes
    clipboard.nodes.forEach(nodeData => {
        const newId = generateNodeId();
        idMap.set(nodeData.originalId, newId);
        
        const newNode = {
            ...nodeData,
            id: newId,
            x: nodeData.x + pasteOffset,
            y: nodeData.y + pasteOffset
        };
        
        delete newNode.originalId;
        
        state.nodes.set(newId, newNode);
        renderNode(newNode);
        
        // Select the new node
        selectNode(newId, true);
    });
    
    // Recreate connections with new IDs
    clipboard.connections.forEach(conn => {
        const newSourceId = idMap.get(conn.source);
        const newTargetId = idMap.get(conn.target);
        
        if (newSourceId && newTargetId) {
            createConnection(newSourceId, newTargetId, conn.sourceOutput, conn.targetInput);
        }
    });
    
    // If this was a cut operation, clear the clipboard
    if (clipboard.isCut) {
        clipboard.nodes = [];
        clipboard.connections = [];
        clipboard.isCut = false;
    }
    
    setModified(true);
    console.log(`Pasted ${idMap.size} nodes`);
}

/**
 * Check if clipboard has content
 */
export function hasClipboardContent() {
    return clipboard.nodes.length > 0;
}
