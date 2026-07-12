// Clipboard management for copy, cut, paste operations
import { state, generateNodeId, setModified, markNodeAdded } from './state.js';
import { renderNode, generateUniqueName } from './nodes.js';
import { createConnection } from './connections.js';
import { selectNode, deselectAllNodes } from './selection.js';

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
    
    // Copy node data. Deep-clone so the clipboard is an independent snapshot -
    // a shallow copy shares the nested `config` object with the live node, so
    // later edits to either would mutate both (and every paste of it).
    state.selectedNodes.forEach(nodeId => {
        const node = state.nodes.get(nodeId);
        if (node) {
            const snapshot = structuredClone(node);
            snapshot.originalId = node.id;
            clipboard.nodes.push(snapshot);
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
    
    // Clear current selection synchronously. (A dynamic import().then() runs as
    // a microtask AFTER the paste loop below has already selected the new
    // nodes, so it would wipe out that fresh selection.)
    deselectAllNodes();

    // Map old IDs to new IDs
    const idMap = new Map();

    // Calculate paste offset (20px down and right from original position).
    // Node x/y and this offset are all CANVAS coordinates, so pasting is
    // zoom-independent by construction - no client->canvas conversion needed.
    const pasteOffset = clipboard.isCut ? 0 : 20;
    
    // Create new nodes
    clipboard.nodes.forEach(nodeData => {
        const newId = generateNodeId();
        idMap.set(nodeData.originalId, newId);
        
        // Generate unique name for pasted node
        const uniqueName = generateUniqueName(nodeData.name, nodeData.type);
        
        // Deep-clone so each pasted node gets its own `config` object rather
        // than sharing the clipboard snapshot's (which repeated pastes would
        // otherwise alias, leaking edits between the copies).
        const newNode = {
            ...structuredClone(nodeData),
            id: newId,
            name: uniqueName,
            x: nodeData.x + pasteOffset,
            y: nodeData.y + pasteOffset
        };

        delete newNode.originalId;
        
        state.nodes.set(newId, newNode);
        renderNode(newNode);
        markNodeAdded(newId);
        
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
