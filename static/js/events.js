// Event handlers
import { state } from './state.js';
import { createNode, deleteNode, deleteNodeAndReconnect } from './nodes.js';
import { deselectNode, deselectAllNodes, selectNode } from './selection.js';
import { deployWorkflow, deployWorkflowFull, clearWorkflow, exportWorkflow, importWorkflow } from './workflow.js';
import { clearDebug } from './debug.js';
import { getConnectionAtPoint, highlightConnectionForInsert, clearConnectionHighlight, getHoveredConnection, insertNodeIntoConnection } from './connections.js';

// Track deploy mode: 'modified' or 'full'
let deployMode = 'modified';

export function setupEventListeners() {
    const nodesContainer = document.getElementById('nodes-container');
    const canvasContainer = document.querySelector('.canvas-container');
    
    // Canvas drop event
    nodesContainer.addEventListener('dragover', handleCanvasDragOver);
    nodesContainer.addEventListener('dragleave', handleCanvasDragLeave);
    nodesContainer.addEventListener('drop', handleCanvasDrop);
    
    // Middle mouse button panning
    setupCanvasPanning(canvasContainer);
    
    // Header buttons - deploy with current mode
    document.getElementById('deploy-btn').addEventListener('click', () => {
        if (deployMode === 'full') {
            deployWorkflowFull();
        } else {
            deployWorkflow();
        }
    });
    document.getElementById('clear-btn').addEventListener('click', clearWorkflow);
    document.getElementById('export-btn').addEventListener('click', exportWorkflow);
    document.getElementById('import-btn').addEventListener('click', importWorkflow);
    document.getElementById('clear-debug-btn').addEventListener('click', clearDebug);
    
    // Deploy dropdown
    const deployDropdownBtn = document.getElementById('deploy-dropdown-btn');
    const deployDropdown = document.getElementById('deploy-dropdown');
    const deployModifiedBtn = document.getElementById('deploy-modified-btn');
    const deployFullBtn = document.getElementById('deploy-full-btn');
    const deployModeIcon = document.getElementById('deploy-mode-icon');
    
    deployDropdownBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        deployDropdown.classList.toggle('hidden');
    });
    
    deployModifiedBtn.addEventListener('click', () => {
        deployMode = 'modified';
        deployModifiedBtn.classList.add('active');
        deployFullBtn.classList.remove('active');
        deployModeIcon.textContent = '◐';
        deployDropdown.classList.add('hidden');
    });
    
    deployFullBtn.addEventListener('click', () => {
        deployMode = 'full';
        deployFullBtn.classList.add('active');
        deployModifiedBtn.classList.remove('active');
        deployModeIcon.textContent = '●';
        deployDropdown.classList.add('hidden');
    });
    
    // Close deploy dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!deployDropdown.classList.contains('hidden') && 
            !deployDropdown.contains(e.target) && 
            e.target !== deployDropdownBtn) {
            deployDropdown.classList.add('hidden');
        }
    });
    
    // Hamburger menu toggle
    const menuBtn = document.getElementById('menu-btn');
    const menuDropdown = document.getElementById('menu-dropdown');
    
    menuBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        menuDropdown.classList.toggle('hidden');
    });
    
    // Close menu when clicking outside
    document.addEventListener('click', (e) => {
        if (!menuDropdown.classList.contains('hidden') && 
            !menuDropdown.contains(e.target) && 
            e.target !== menuBtn) {
            menuDropdown.classList.add('hidden');
        }
    });
    
    // Close menu after clicking a menu item
    document.getElementById('clear-btn').addEventListener('click', () => {
        menuDropdown.classList.add('hidden');
    });
    
    document.getElementById('export-btn').addEventListener('click', () => {
        menuDropdown.classList.add('hidden');
    });
    
    document.getElementById('import-btn').addEventListener('click', () => {
        menuDropdown.classList.add('hidden');
    });
    
    // Close properties button
    document.getElementById('close-properties-btn').addEventListener('click', () => {
        const propertiesPanel = document.getElementById('properties-panel-container');
        propertiesPanel.classList.add('hidden');
    });
    
    // Sidebar tab switching
    document.querySelectorAll('.sidebar-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const panelId = tab.dataset.panel;
            
            // Update active tab
            document.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            // Show corresponding panel
            document.querySelectorAll('.sidebar-panel').forEach(p => p.classList.remove('active'));
            document.getElementById(`${panelId}-panel`).classList.add('active');
        });
    });
    
    // Debug filter controls
    document.getElementById('filter-info').addEventListener('click', (e) => {
        e.currentTarget.classList.toggle('active');
        const isActive = e.currentTarget.classList.contains('active');
        import('./debug.js').then(({ toggleInfoMessages }) => {
            toggleInfoMessages(isActive);
        });
    });
    
    document.getElementById('filter-errors').addEventListener('click', (e) => {
        e.currentTarget.classList.toggle('active');
        const isActive = e.currentTarget.classList.contains('active');
        import('./debug.js').then(({ toggleErrorMessages }) => {
            toggleErrorMessages(isActive);
        });
    });
    
    document.getElementById('collapse-similar').addEventListener('click', (e) => {
        e.currentTarget.classList.toggle('active');
        const isActive = e.currentTarget.classList.contains('active');
        import('./debug.js').then(({ toggleCollapseSimilar }) => {
            toggleCollapseSimilar(isActive);
        });
    });
    
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
        // Check if user is typing in an input field
        const isInputField = e.target.tagName === 'INPUT' || 
                           e.target.tagName === 'TEXTAREA' || 
                           e.target.isContentEditable;
        
        if (e.key === 'Escape') {
            deselectAllNodes();
        }
        
        if (e.key === 'Delete') {
            console.log('Delete key pressed, selectedNodes:', state.selectedNodes.size, 'selectedConnection:', state.selectedConnection);
            if (state.selectedNodes.size > 0) {
                // Save state before deleting
                import('./history.js').then(({ saveState }) => {
                    saveState('delete nodes');
                });
                
                const nodesToDelete = Array.from(state.selectedNodes);
                
                if (e.ctrlKey || e.metaKey) {
                    // Ctrl+Delete: Delete and reconnect nodes on either side
                    nodesToDelete.forEach(nodeId => deleteNodeAndReconnect(nodeId));
                } else {
                    // Normal Delete: Just delete the nodes
                    nodesToDelete.forEach(nodeId => deleteNode(nodeId));
                }
                deselectAllNodes();
            } else if (state.selectedConnection) {
                console.log('Deleting selected connection');
                import('./history.js').then(({ saveState }) => {
                    saveState('delete connection');
                });
                import('./connections.js').then(({ deleteSelectedConnection }) => {
                    deleteSelectedConnection();
                });
            }
        }
        
        // Copy (Ctrl+C or Cmd+C)
        if ((e.ctrlKey || e.metaKey) && e.key === 'c' && !isInputField) {
            e.preventDefault();
            import('./clipboard.js').then(({ copySelectedNodes }) => {
                copySelectedNodes();
            });
        }
        
        // Cut (Ctrl+X or Cmd+X)
        if ((e.ctrlKey || e.metaKey) && e.key === 'x' && !isInputField) {
            e.preventDefault();
            import('./clipboard.js').then(({ cutSelectedNodes }) => {
                cutSelectedNodes();
            });
            import('./history.js').then(({ saveState }) => {
                saveState('cut nodes');
            });
        }
        
        // Paste (Ctrl+V or Cmd+V)
        if ((e.ctrlKey || e.metaKey) && e.key === 'v' && !isInputField) {
            e.preventDefault();
            import('./clipboard.js').then(({ pasteNodes }) => {
                pasteNodes();
            });
            import('./history.js').then(({ saveState }) => {
                saveState('paste nodes');
            });
        }
        
        // Undo (Ctrl+Z or Cmd+Z)
        if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey && !isInputField) {
            e.preventDefault();
            import('./history.js').then(({ undo }) => {
                undo();
            });
        }
        
        // Redo (Ctrl+Y or Cmd+Shift+Z)
        if (((e.ctrlKey && e.key === 'y') || (e.metaKey && e.shiftKey && e.key === 'z')) && !isInputField) {
            e.preventDefault();
            import('./history.js').then(({ redo }) => {
                redo();
            });
        }
    });
    
    setupSelectionBox();
}

function togglePropertiesPanel() {
    const propertiesPanel = document.getElementById('properties-panel-container');
    propertiesPanel.classList.toggle('hidden');
}

// Throttle helper for dragover
let lastDragOverTime = 0;
const DRAG_THROTTLE_MS = 50; // Only check every 50ms

function handleCanvasDragOver(e) {
    e.preventDefault();
    
    // Throttle the connection check for performance
    const now = Date.now();
    if (now - lastDragOverTime < DRAG_THROTTLE_MS) {
        return;
    }
    lastDragOverTime = now;
    
    // Check if dragging over a connection and highlight it
    const canvasRect = document.getElementById('canvas').getBoundingClientRect();
    const x = e.clientX - canvasRect.left;
    const y = e.clientY - canvasRect.top;
    
    const hoveredConnection = getConnectionAtPoint(x, y);
    if (hoveredConnection) {
        highlightConnectionForInsert(hoveredConnection);
    } else {
        clearConnectionHighlight();
    }
}

function handleCanvasDragLeave(e) {
    // Clear highlight when leaving the canvas
    clearConnectionHighlight();
}

function handleCanvasDrop(e) {
    e.preventDefault();
    
    // Get the hovered connection before clearing
    const connectionToInsertInto = getHoveredConnection();
    
    // Clear any connection highlight
    clearConnectionHighlight();
    
    const nodeType = e.dataTransfer.getData('nodeType');
    if (!nodeType) return;
    
    // Get the drag offset from where the user clicked on the palette item
    const offsetX = parseFloat(e.dataTransfer.getData('dragOffsetX')) || 0;
    const offsetY = parseFloat(e.dataTransfer.getData('dragOffsetY')) || 0;
    
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left - offsetX;
    const y = e.clientY - rect.top - offsetY;
    
    const newNodeId = createNode(nodeType, x, y);
    
    // If dropped on a connection, insert the node into it
    if (connectionToInsertInto && newNodeId) {
        // Small delay to ensure node is fully rendered
        setTimeout(() => {
            insertNodeIntoConnection(newNodeId, connectionToInsertInto);
        }, 50);
    }
}

function setupSelectionBox() {
    const canvasContainer = document.querySelector('.canvas-container');
    
    canvasContainer.addEventListener('mousedown', (e) => {
        // Only start selection box with left mouse button (button === 0)
        if (e.button !== 0) return;
        
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

function setupCanvasPanning(canvasContainer) {
    let isPanning = false;
    let startScrollLeft = 0;
    let startScrollTop = 0;
    let startX = 0;
    let startY = 0;
    
    canvasContainer.addEventListener('mousedown', (e) => {
        // Middle mouse button (button === 1)
        if (e.button === 1) {
            isPanning = true;
            startScrollLeft = canvasContainer.scrollLeft;
            startScrollTop = canvasContainer.scrollTop;
            startX = e.clientX;
            startY = e.clientY;
            canvasContainer.style.cursor = 'grabbing';
            e.preventDefault();
        }
    });
    
    canvasContainer.addEventListener('mousemove', (e) => {
        if (!isPanning) return;
        
        const deltaX = e.clientX - startX;
        const deltaY = e.clientY - startY;
        
        canvasContainer.scrollLeft = startScrollLeft - deltaX;
        canvasContainer.scrollTop = startScrollTop - deltaY;
    });
    
    canvasContainer.addEventListener('mouseup', (e) => {
        if (e.button === 1) {
            isPanning = false;
            canvasContainer.style.cursor = '';
        }
    });
    
    canvasContainer.addEventListener('mouseleave', () => {
        if (isPanning) {
            isPanning = false;
            canvasContainer.style.cursor = '';
        }
    });
    
    // Prevent context menu on middle click
    canvasContainer.addEventListener('contextmenu', (e) => {
        if (e.button === 1) {
            e.preventDefault();
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
