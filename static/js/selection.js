// Selection management
import { state } from './state.js';
import { renderProperties } from './properties.js';

export function selectNode(nodeId, addToSelection = false) {
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

export function deselectNode() {
    if (state.selectedNode) {
        const nodeEl = document.getElementById(`node-${state.selectedNode}`);
        if (nodeEl) nodeEl.classList.remove('selected');
    }
    state.selectedNode = null;
    
    document.getElementById('properties-panel').innerHTML = 
        '<p class="placeholder">Select a node to edit properties</p>';
}

export function deselectAllNodes() {
    state.selectedNodes.forEach(nodeId => {
        const nodeEl = document.getElementById(`node-${nodeId}`);
        if (nodeEl) nodeEl.classList.remove('selected');
    });
    state.selectedNodes.clear();
    state.selectedNode = null;
    
    document.getElementById('properties-panel').innerHTML = 
        '<p class="placeholder">Select a node to edit properties</p>';
}
