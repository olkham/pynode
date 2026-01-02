// Selection management
import { state, getNodeType } from './state.js';
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
