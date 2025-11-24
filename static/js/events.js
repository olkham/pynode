// Event handlers
import { state } from './state.js';
import { createNode } from './nodes.js';
import { deselectNode, deselectAllNodes, selectNode } from './selection.js';
import { deleteNode } from './nodes.js';
import { deployWorkflow, clearWorkflow, exportWorkflow, importWorkflow } from './workflow.js';
import { clearDebug } from './debug.js';

export function setupEventListeners() {
    const nodesContainer = document.getElementById('nodes-container');
    
    // Canvas drop event
    nodesContainer.addEventListener('dragover', (e) => e.preventDefault());
    nodesContainer.addEventListener('drop', handleCanvasDrop);
    
    // Header buttons
    document.getElementById('deploy-btn').addEventListener('click', deployWorkflow);
    document.getElementById('clear-btn').addEventListener('click', clearWorkflow);
    document.getElementById('export-btn').addEventListener('click', exportWorkflow);
    document.getElementById('import-btn').addEventListener('click', importWorkflow);
    document.getElementById('clear-debug-btn').addEventListener('click', clearDebug);
    
    // Properties panel resize
    setupPropertiesResize();
    
    // Canvas click to deselect
    nodesContainer.addEventListener('click', (e) => {
        if (e.target === nodesContainer) {
            deselectNode();
        }
    });
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            deselectAllNodes();
        }
        
        if (e.key === 'Delete' && state.selectedNodes.size > 0) {
            const nodesToDelete = Array.from(state.selectedNodes);
            nodesToDelete.forEach(nodeId => deleteNode(nodeId));
            deselectAllNodes();
        }
    });
    
    setupSelectionBox();
}

function handleCanvasDrop(e) {
    e.preventDefault();
    const nodeType = e.dataTransfer.getData('nodeType');
    if (!nodeType) return;
    
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    createNode(nodeType, x, y);
}

function setupSelectionBox() {
    const canvasContainer = document.querySelector('.canvas-container');
    
    canvasContainer.addEventListener('mousedown', (e) => {
        const isNode = e.target.closest('.node');
        const isPort = e.target.classList.contains('port');
        
        if (isNode || isPort) return;
        
        if (!e.ctrlKey && !e.metaKey) {
            deselectAllNodes();
        }
        
        state.selectionStart = { x: e.clientX, y: e.clientY };
        state.selectionBox = document.createElement('div');
        state.selectionBox.className = 'selection-box';
        state.selectionBox.style.left = `${e.clientX}px`;
        state.selectionBox.style.top = `${e.clientY}px`;
        state.selectionBox.style.width = '0';
        state.selectionBox.style.height = '0';
        document.body.appendChild(state.selectionBox);
        
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!state.selectionBox || !state.selectionStart) return;
        
        const currentX = e.clientX;
        const currentY = e.clientY;
        const startX = state.selectionStart.x;
        const startY = state.selectionStart.y;
        
        const left = Math.min(startX, currentX);
        const top = Math.min(startY, currentY);
        const width = Math.abs(currentX - startX);
        const height = Math.abs(currentY - startY);
        
        state.selectionBox.style.left = `${left}px`;
        state.selectionBox.style.top = `${top}px`;
        state.selectionBox.style.width = `${width}px`;
        state.selectionBox.style.height = `${height}px`;
        
        const nodesInBox = new Set();
        
        state.nodes.forEach((nodeData, nodeId) => {
            const nodeEl = document.getElementById(`node-${nodeId}`);
            if (!nodeEl) return;
            
            const rect = nodeEl.getBoundingClientRect();
            const boxLeft = left;
            const boxTop = top;
            const boxRight = left + width;
            const boxBottom = top + height;
            
            if (rect.left < boxRight && rect.right > boxLeft && 
                rect.top < boxBottom && rect.bottom > boxTop) {
                nodesInBox.add(nodeId);
            }
        });
        
        nodesInBox.forEach(nodeId => {
            if (!state.selectedNodes.has(nodeId)) {
                state.selectedNodes.add(nodeId);
                const nodeEl = document.getElementById(`node-${nodeId}`);
                if (nodeEl) nodeEl.classList.add('selected');
            }
        });
    });
    
    document.addEventListener('mouseup', () => {
        if (state.selectionBox) {
            state.selectionBox.remove();
            state.selectionBox = null;
            state.selectionStart = null;
        }
    });
}

function setupPropertiesResize() {
    const resizeHandle = document.getElementById('properties-resize-handle');
    const propertiesPanel = document.getElementById('properties-panel-container');
    
    if (!resizeHandle || !propertiesPanel) return;
    
    let isResizing = false;
    let startX = 0;
    let startWidth = 0;
    
    resizeHandle.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = propertiesPanel.offsetWidth;
        propertiesPanel.classList.add('resizing');
        document.body.style.cursor = 'ew-resize';
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        
        const deltaX = startX - e.clientX;
        const newWidth = startWidth + deltaX;
        
        // Respect min and max width constraints
        if (newWidth >= 250 && newWidth <= 800) {
            propertiesPanel.style.width = `${newWidth}px`;
        }
    });
    
    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            propertiesPanel.classList.remove('resizing');
            document.body.style.cursor = '';
        }
    });
}
