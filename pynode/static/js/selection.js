// Selection management
import { state, getNodeType } from './state.js';
import { renderProperties } from './properties.js';
import { updateConnections } from './connections.js';

/**
 * Find the shortest path between two nodes using BFS.
 * Returns an object with arrays of node IDs and connections on the path,
 * or null if no path exists.
 */
export function findPathBetweenNodes(nodeId1, nodeId2) {
    if (nodeId1 === nodeId2) {
        return { nodes: [nodeId1], connections: [] };
    }
    
    // Build adjacency list for bidirectional graph traversal
    // We need to find path regardless of connection direction
    const adjacency = new Map();
    
    state.nodes.forEach((_, nodeId) => {
        adjacency.set(nodeId, []);
    });
    
    state.connections.forEach(conn => {
        // Add both directions for path finding
        if (adjacency.has(conn.source)) {
            adjacency.get(conn.source).push({ 
                node: conn.target, 
                connection: conn,
                direction: 'forward'
            });
        }
        if (adjacency.has(conn.target)) {
            adjacency.get(conn.target).push({ 
                node: conn.source, 
                connection: conn,
                direction: 'backward'
            });
        }
    });
    
    // BFS to find shortest path
    const visited = new Set();
    const queue = [{ nodeId: nodeId1, path: [nodeId1], connections: [] }];
    visited.add(nodeId1);
    
    while (queue.length > 0) {
        const { nodeId, path, connections } = queue.shift();
        
        const neighbors = adjacency.get(nodeId) || [];
        for (const { node: neighborId, connection } of neighbors) {
            if (neighborId === nodeId2) {
                // Found the target
                return {
                    nodes: [...path, neighborId],
                    connections: [...connections, connection]
                };
            }
            
            if (!visited.has(neighborId)) {
                visited.add(neighborId);
                queue.push({
                    nodeId: neighborId,
                    path: [...path, neighborId],
                    connections: [...connections, connection]
                });
            }
        }
    }
    
    // No path found
    return null;
}

/**
 * Select the path between two nodes (all nodes and connections on the path).
 * Returns true if a path was found and selected, false otherwise.
 */
export function selectPathBetweenNodes(nodeId1, nodeId2) {
    const path = findPathBetweenNodes(nodeId1, nodeId2);
    
    if (!path) {
        console.log('No path found between nodes:', nodeId1, nodeId2);
        return false;
    }
    
    // Clear current selection
    deselectAllNodes(true);
    clearSelectedConnections();
    
    // Select all nodes on the path
    path.nodes.forEach(nodeId => {
        state.selectedNodes.add(nodeId);
        const nodeEl = document.getElementById(`node-${nodeId}`);
        if (nodeEl) nodeEl.classList.add('selected');
    });
    
    // Set the last clicked node as the primary selected node
    state.selectedNode = nodeId2;
    
    // Select all connections on the path
    path.connections.forEach(conn => {
        const connKey = `${conn.source}->${conn.target}:${conn.sourceOutput || 0}`;
        state.selectedConnections.add(connKey);
    });
    
    // Update connection visuals
    updateConnections();
    
    // Update info panel for the clicked node
    updateInfoPanel(nodeId2);
    
    // Update properties panel
    const propertiesPanel = document.getElementById('properties-panel-container');
    const wasPanelOpen = propertiesPanel && !propertiesPanel.classList.contains('hidden');
    if (wasPanelOpen) {
        document.getElementById('properties-panel').innerHTML = 
            `<p class="placeholder">${path.nodes.length} nodes selected (path)</p>`;
    }
    
    console.log('Selected path:', path.nodes.length, 'nodes,', path.connections.length, 'connections');
    return true;
}

/**
 * Clear all selected connections
 */
export function clearSelectedConnections() {
    state.selectedConnections.clear();
    state.selectedConnection = null;
}

export function selectNode(nodeId, addToSelection = false) {
    // Check if properties panel is open BEFORE deselecting (which would close it)
    const propertiesPanel = document.getElementById('properties-panel-container');
    const wasPanelOpen = propertiesPanel && !propertiesPanel.classList.contains('hidden');
    
    if (!addToSelection) {
        deselectAllNodes(true);  // Pass flag to keep panel open
    }
    
    state.selectedNode = nodeId;
    state.selectedNodes.add(nodeId);
    const nodeEl = document.getElementById(`node-${nodeId}`);
    if (nodeEl) nodeEl.classList.add('selected');
    
    // Update the information panel
    updateInfoPanel(nodeId);
    
    // If properties panel was open, update it with the new node's properties
    if (wasPanelOpen) {
        const nodeData = state.nodes.get(nodeId);
        if (state.selectedNodes.size === 1) {
            renderProperties(nodeData);
        } else {
            document.getElementById('properties-panel').innerHTML = 
                `<p class="placeholder">${state.selectedNodes.size} nodes selected</p>`;
        }
    }
}

function updateInfoPanel(nodeId) {
    const infoContent = document.querySelector('#info-panel .info-content');
    if (!infoContent) return;
    
    const nodeData = state.nodes.get(nodeId);
    if (!nodeData) {
        infoContent.innerHTML = '<p class="placeholder">Select a node to see information</p>';
        return;
    }
    
    const nodeType = getNodeType(nodeData.type);
    if (!nodeType || !nodeType.info) {
        infoContent.innerHTML = `<p class="placeholder">No information available for ${nodeType?.name || nodeData.type}</p>`;
        return;
    }
    
    infoContent.innerHTML = `
        <div class="info-node-header">
            <span class="info-node-icon">${nodeType.icon}</span>
            <span class="info-node-name">${nodeType.name}</span>
        </div>
        <div class="info-node-content">${nodeType.info}</div>
    `;
}

function clearInfoPanel() {
    const infoContent = document.querySelector('#info-panel .info-content');
    if (infoContent) {
        infoContent.innerHTML = '<p class="placeholder">Select a node to see information</p>';
    }
}

export function deselectNode() {
    if (state.selectedNode) {
        const nodeEl = document.getElementById(`node-${state.selectedNode}`);
        if (nodeEl) nodeEl.classList.remove('selected');
    }
    state.selectedNode = null;
    
    // Clear the info panel
    clearInfoPanel();
    
    // Hide the properties panel
    const propertiesPanel = document.getElementById('properties-panel-container');
    if (propertiesPanel) {
        propertiesPanel.classList.add('hidden');
    }
}

export function deselectAllNodes(keepPanelOpen = false) {
    state.selectedNodes.forEach(nodeId => {
        const nodeEl = document.getElementById(`node-${nodeId}`);
        if (nodeEl) nodeEl.classList.remove('selected');
    });
    state.selectedNodes.clear();
    state.selectedNode = null;
    
    // Clear selected connections as well
    if (state.selectedConnections.size > 0) {
        state.selectedConnections.clear();
        updateConnections();
    }
    
    // Clear the info panel
    clearInfoPanel();
    
    // Hide the properties panel (unless told to keep it open)
    if (!keepPanelOpen) {
        const propertiesPanel = document.getElementById('properties-panel-container');
        if (propertiesPanel) {
            propertiesPanel.classList.add('hidden');
        }
    }
}
