// Selection management
import { state } from './state.js';
import { renderProperties } from './properties.js';

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

export function deselectNode() {
    if (state.selectedNode) {
        const nodeEl = document.getElementById(`node-${state.selectedNode}`);
        if (nodeEl) nodeEl.classList.remove('selected');
    }
    state.selectedNode = null;
    
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
    
    // Hide the properties panel (unless told to keep it open)
    if (!keepPanelOpen) {
        const propertiesPanel = document.getElementById('properties-panel-container');
        if (propertiesPanel) {
            propertiesPanel.classList.add('hidden');
        }
    }
}
