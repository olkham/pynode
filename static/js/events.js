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
        if (e.target === nodesContainer && !state.justSelectedConnection) {
            deselectNode();
            import('./connections.js').then(({ deselectConnection }) => {
                deselectConnection();
            });
        }
    });
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            deselectAllNodes();
        }
        
        if (e.key === 'Delete') {
            console.log('Delete key pressed, selectedNodes:', state.selectedNodes.size, 'selectedConnection:', state.selectedConnection);
            if (state.selectedNodes.size > 0) {
                const nodesToDelete = Array.from(state.selectedNodes);
                nodesToDelete.forEach(nodeId => deleteNode(nodeId));
                deselectAllNodes();
            } else if (state.selectedConnection) {
                console.log('Deleting selected connection');
                import('./connections.js').then(({ deleteSelectedConnection }) => {
                    deleteSelectedConnection();
                });
            }
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
        const isSvgPath = e.target.tagName === 'path';
        
        // Don't start selection box if clicking on node, port, or connection
        if (isNode || isPort || isSvgPath) return;
        
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
            // Check if we should select a connection instead of nodes
            const boxRect = state.selectionBox.getBoundingClientRect();
            const boxLeft = boxRect.left;
            const boxTop = boxRect.top;
            const boxRight = boxRect.right;
            const boxBottom = boxRect.bottom;
            
            // If selection box is very small (like a click), check for connection intersection
            const isSmallBox = boxRect.width < 50 && boxRect.height < 50;
            
            if (isSmallBox) {
                // Check if any connection path intersects with the selection box
                const paths = document.querySelectorAll('#connections path');
                let foundConnection = null;
                
                console.log('Checking connections, found paths:', paths.length);
                
                paths.forEach(path => {
                    const pathRect = path.getBoundingClientRect();
                    
                    console.log('Path rect:', pathRect, 'Box:', { boxLeft, boxTop, boxRight, boxBottom });
                    
                    // Check if path bounding box intersects with selection box
                    if (pathRect.left < boxRight && pathRect.right > boxLeft && 
                        pathRect.top < boxBottom && pathRect.bottom > boxTop) {
                        // Get connection data from path attributes
                        const source = path.getAttribute('data-source');
                        const target = path.getAttribute('data-target');
                        const sourceOutput = parseInt(path.getAttribute('data-source-output') || '0');
                        
                        console.log('Found intersecting connection:', source, target, sourceOutput);
                        
                        if (source && target) {
                            foundConnection = { source, target, sourceOutput };
                        }
                    }
                });
                
                if (foundConnection) {
                    // Select the connection
                    console.log('Attempting to select connection:', foundConnection);
                    import('./connections.js').then(({ selectConnection }) => {
                        console.log('selectConnection function loaded:', typeof selectConnection);
                        selectConnection(foundConnection.source, foundConnection.target, foundConnection.sourceOutput);
                    });
                    
                    // Prevent canvas click from deselecting immediately
                    setTimeout(() => {
                        state.justSelectedConnection = false;
                    }, 100);
                    state.justSelectedConnection = true;
                }
            }
            
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
