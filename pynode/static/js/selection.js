// Selection management
import { state, getNodeType } from './state.js';
import { renderProperties } from './properties.js';
import { updateConnections } from './connections.js';

/**
 * Find the shortest path between two nodes using BFS.
 * Returns an object with arrays of node IDs and connections on the path,
 * or null if no path exists.
 */
/**
 * Find all simple paths between two nodes using DFS (with limits).
 * Returns an array of path objects: { nodes: [...], connections: [...] }
 * Limits: `maxPaths` and `maxDepth` to avoid combinatorial explosion.
 */
export function findAllPathsBetweenNodes(nodeId1, nodeId2, { maxPaths = 200, maxDepth = 100 } = {}) {
    if (nodeId1 === nodeId2) {
        return [{ nodes: [nodeId1], connections: [] }];
    }

    // Build adjacency list for bidirectional graph traversal
    const adjacency = new Map();
    state.nodes.forEach((_, nodeId) => {
        adjacency.set(nodeId, []);
    });

    state.connections.forEach(conn => {
        if (adjacency.has(conn.source)) {
            adjacency.get(conn.source).push({ node: conn.target, connection: conn });
        }
        if (adjacency.has(conn.target)) {
            adjacency.get(conn.target).push({ node: conn.source, connection: conn });
        }
    });

    const results = [];

    // DFS stack: node, path nodes array, connections array
    const stack = [{ node: nodeId1, path: [nodeId1], connections: [] }];

    while (stack.length > 0 && results.length < maxPaths) {
        const { node, path, connections } = stack.pop();

        if (path.length > maxDepth) continue;

        const neighbors = adjacency.get(node) || [];
        for (const { node: neighborId, connection } of neighbors) {
            // avoid cycles in current path
            if (path.includes(neighborId)) continue;

            const newPath = [...path, neighborId];
            const newConns = [...connections, connection];

            if (neighborId === nodeId2) {
                results.push({ nodes: newPath, connections: newConns });
                if (results.length >= maxPaths) break;
            } else {
                stack.push({ node: neighborId, path: newPath, connections: newConns });
            }
        }
    }

    return results;
}

// Backwards-compatible single-path finder: returns first found path or null
export function findPathBetweenNodes(nodeId1, nodeId2) {
    const all = findAllPathsBetweenNodes(nodeId1, nodeId2, { maxPaths: 1 });
    return all.length > 0 ? all[0] : null;
}

/**
 * Select the path between two nodes (all nodes and connections on the path).
 * Returns true if a path was found and selected, false otherwise.
 */
export function selectPathBetweenNodes(nodeId1, nodeId2) {
    const paths = findAllPathsBetweenNodes(nodeId1, nodeId2);

    if (!paths || paths.length === 0) {
        console.log('No path found between nodes:', nodeId1, nodeId2);
        return false;
    }

    // Clear current selection
    deselectAllNodes(true);
    clearSelectedConnections();

    // Aggregate nodes and connections across all found paths
    const nodesSet = new Set();
    const connSet = new Set();

    paths.forEach(path => {
        path.nodes.forEach(n => nodesSet.add(n));
        path.connections.forEach(conn => {
            const key = `${conn.source}->${conn.target}:${conn.sourceOutput || 0}`;
            connSet.add(key);
        });
    });

    // Select aggregated nodes
    nodesSet.forEach(nodeId => {
        state.selectedNodes.add(nodeId);
        const nodeEl = document.getElementById(`node-${nodeId}`);
        if (nodeEl) nodeEl.classList.add('selected');
    });

    // Set the last clicked node as the primary selected node
    state.selectedNode = nodeId2;

    // Select aggregated connections
    connSet.forEach(k => state.selectedConnections.add(k));

    // Update visuals
    updateConnections();

    // Update info panel for the clicked node
    updateInfoPanel(nodeId2);

    // Update properties panel
    const propertiesPanel = document.getElementById('properties-panel-container');
    const wasPanelOpen = propertiesPanel && !propertiesPanel.classList.contains('hidden');
    if (wasPanelOpen) {
        document.getElementById('properties-panel').innerHTML = 
            `<p class="placeholder">${nodesSet.size} nodes selected (${paths.length} path(s))</p>`;
    }

    console.log('Selected paths:', paths.length, 'paths,', nodesSet.size, 'unique nodes,', connSet.size, 'connections');
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
