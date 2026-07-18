// Event handlers
import { state } from './state.js';
import { createNode, deleteNode, deleteNodeAndReconnect, snapNodeToGrid } from './nodes.js';
import { deselectNode, deselectAllNodes, selectNode } from './selection.js';
import { deployWorkflow, deployWorkflowFull, restartWorkflow, stopWorkflow, clearWorkflow, exportWorkflow, importWorkflow, fetchExamples, loadExampleWorkflow } from './workflow.js';
import { clearDebug, toggleDebugPaused } from './debug.js';
import { getConnectionAtPoint, highlightConnectionForInsert, clearConnectionHighlight, getHoveredConnection, insertNodeIntoConnection } from './connections.js';
import { clientToCanvas, getZoom } from './viewport.js';

// Track deploy mode: 'modified' or 'full'
let deployMode = 'modified';

// Populate the Examples submenu from the bundled manifest on first open, then
// cache. Kept standalone (looks elements up by id) so it does not depend on the
// setupEventListeners closure.
function setupExamplesSubmenu() {
    const submenu = document.getElementById('examples-btn')?.closest('.menu-submenu');
    const listEl = document.getElementById('examples-list');
    if (!submenu || !listEl) return;

    let loaded = false;

    const closeMenu = () => {
        document.getElementById('menu-dropdown')?.classList.add('hidden');
        document.getElementById('examples-submenu')?.classList.add('hidden');
    };

    const populate = async () => {
        if (loaded) return;
        loaded = true;  // guard against concurrent hovers; reset on error below
        try {
            const examples = await fetchExamples();
            listEl.innerHTML = '';
            if (!examples.length) {
                listEl.innerHTML = '<div class="examples-placeholder">No examples found</div>';
                return;
            }
            examples.forEach(example => {
                const item = document.createElement('button');
                item.className = 'menu-item example-item';
                item.title = example.description || '';
                item.innerHTML =
                    `<span class="example-title">${escapeHtml(example.title || example.id)}</span>` +
                    (example.description ? `<span class="example-desc">${escapeHtml(example.description)}</span>` : '') +
                    (example.requires ? `<span class="example-requires">${escapeHtml(example.requires)}</span>` : '');
                item.addEventListener('click', async () => {
                    closeMenu();
                    await loadExampleWorkflow(example);
                });
                listEl.appendChild(item);
            });
        } catch (error) {
            console.error('Failed to load examples:', error);
            listEl.innerHTML = '<div class="examples-placeholder">Could not load examples</div>';
            loaded = false;  // allow a retry next time the submenu opens
        }
    };

    // Trigger population the first time the user reaches for the submenu.
    submenu.addEventListener('mouseenter', populate);
    submenu.addEventListener('focusin', populate);
    document.getElementById('examples-btn')?.addEventListener('click', populate);
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

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
    // Export submenu: default is Export Flow, also support Export Selected
    const exportBtn = document.getElementById('export-btn');
    const exportSubmenu = document.getElementById('export-submenu');
    const exportFlowBtn = document.getElementById('export-flow-btn');
    const exportSelectedBtn = document.getElementById('export-selected-btn');

    // Submenu display handled via CSS hover/focus; no click toggle here.

    if (exportFlowBtn) {
        exportFlowBtn.addEventListener('click', () => {
            exportWorkflow();
            menuDropdown.classList.add('hidden');
            exportSubmenu.classList.add('hidden');
        });
    }

    if (exportSelectedBtn) {
        exportSelectedBtn.addEventListener('click', () => {
            // Lazy-import to avoid circular deps
            import('./workflow.js').then(({ exportSelected }) => {
                exportSelected();
            });
            menuDropdown.classList.add('hidden');
            exportSubmenu.classList.add('hidden');
        });
    }

    document.getElementById('import-btn').addEventListener('click', importWorkflow);

    // Examples submenu: lazily populated from the bundled manifest the first
    // time the user opens it, then cached.
    setupExamplesSubmenu();

    document.getElementById('clear-debug-btn').addEventListener('click', clearDebug);

    // Pause/resume debug list updates. While paused the button pulses and
    // shows a play icon as a reminder that new messages are being withheld.
    // Plain SVG (currentColor) instead of emoji glyphs for a crisp, theme-
    // consistent icon instead of the platform's (often colored) emoji font.
    const PAUSE_ICON = `<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"><rect x="3" y="2" width="4" height="12" rx="1"></rect><rect x="9" y="2" width="4" height="12" rx="1"></rect></svg>`;
    const PLAY_ICON = `<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"><path d="M4 2.5v11l10-5.5z"></path></svg>`;
    const pauseDebugBtn = document.getElementById('pause-debug-btn');
    if (pauseDebugBtn) {
        pauseDebugBtn.innerHTML = PAUSE_ICON;
        pauseDebugBtn.addEventListener('click', () => {
            const paused = toggleDebugPaused();
            pauseDebugBtn.classList.toggle('debug-paused-active', paused);
            pauseDebugBtn.innerHTML = paused ? PLAY_ICON : PAUSE_ICON;
            pauseDebugBtn.title = paused ? 'Resume updates (paused)' : 'Pause updates';
        });
    }
    
    // Add workflow button
    const addWorkflowBtn = document.getElementById('add-workflow-btn');
    if (addWorkflowBtn) {
        addWorkflowBtn.addEventListener('click', () => {
            import('./workflows.js').then(({ createNewWorkflow }) => {
                createNewWorkflow();
            });
        });
    }
    
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
    
    // Restart button
    const deployRestartBtn = document.getElementById('deploy-restart-btn');
    deployRestartBtn.addEventListener('click', () => {
        restartWorkflow();
        deployDropdown.classList.add('hidden');
    });

    // Stop button - an action like Restart, not a deploy mode: it does not
    // change the selected Modified/Full mode.
    const deployStopBtn = document.getElementById('deploy-stop-btn');
    deployStopBtn.addEventListener('click', () => {
        stopWorkflow();
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

    // Submenu visibility is managed by CSS (:hover / :focus-within).

    document.getElementById('import-btn').addEventListener('click', () => {
        menuDropdown.classList.add('hidden');
        if (exportSubmenu) exportSubmenu.classList.add('hidden');
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

    // Left palette + right sidebar resize/toggle handles
    setupSidePanelGrabs();
    
    // Canvas click to deselect or select connections
    nodesContainer.addEventListener('click', (e) => {
        if (e.target === nodesContainer && !state.justSelectedConnection) {
            // Check if clicking near a connection
            import('./connections.js').then(({ getConnectionAtPoint, selectConnection, deselectConnection }) => {
                // Get click coordinates in canvas (SVG) space, zoom-aware.
                // Threshold scales with 1/zoom so the click slop stays ~20 screen px.
                const canvasPoint = clientToCanvas(e.clientX, e.clientY);

                const clickedConnection = getConnectionAtPoint(canvasPoint.x, canvasPoint.y, 20 / getZoom());
                if (clickedConnection) {
                    // Select the connection
                    selectConnection(clickedConnection.source, clickedConnection.target, clickedConnection.sourceOutput);
                    state.justSelectedConnection = true;
                    setTimeout(() => {
                        state.justSelectedConnection = false;
                    }, 100);
                } else {
                    // Deselect everything
                    deselectNode();
                    deselectConnection();
                }
            });
        }
    });
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Check if user is actively editing a form field (use activeElement, not e.target
        // which is always the document for listeners attached to document).
        // Only text-entry controls swallow Delete/Backspace - non-text inputs
        // (checkboxes, buttons, etc.) must not block node deletion.
        const activeEl = document.activeElement;
        const NON_TEXT_INPUT_TYPES = ['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file'];
        const isEditingInput = activeEl && (
            (activeEl.tagName === 'INPUT' && !NON_TEXT_INPUT_TYPES.includes(activeEl.type)) ||
            activeEl.tagName === 'TEXTAREA' ||
            activeEl.tagName === 'SELECT' ||
            activeEl.isContentEditable
        );
        
        if (e.key === 'Escape') {
            deselectAllNodes();
            // Return focus to the canvas so keyboard shortcuts work immediately
            const canvas = document.getElementById('canvas');
            if (canvas) canvas.focus();
        }
        
        // Delete works unless user is actively editing a text field
        if ((e.key === 'Delete' || e.key === 'Backspace') && !isEditingInput) {
            console.log('Delete key pressed, selectedNodes:', state.selectedNodes.size, 'selectedConnection:', state.selectedConnection);
            if (state.selectedNodes.size > 0) {
                const nodesToDelete = Array.from(state.selectedNodes);
                
                // Save state before deleting - must be sync or await
                import('./history.js').then(({ saveState }) => {
                    saveState('delete nodes');
                    
                    if (e.ctrlKey || e.metaKey) {
                        // Ctrl+Delete: Delete and reconnect nodes on either side
                        nodesToDelete.forEach(nodeId => deleteNodeAndReconnect(nodeId));
                    } else {
                        // Normal Delete: Just delete the nodes
                        nodesToDelete.forEach(nodeId => deleteNode(nodeId));
                    }
                    deselectAllNodes();
                });
            } else if (state.selectedConnection) {
                console.log('Deleting selected connection');
                import('./history.js').then(({ saveState }) => {
                    saveState('delete connection');
                    import('./connections.js').then(({ deleteSelectedConnection }) => {
                        deleteSelectedConnection();
                    });
                });
            }
        }
        
        // Copy (Ctrl+C or Cmd+C)
        if ((e.ctrlKey || e.metaKey) && e.key === 'c' && !isEditingInput) {
            e.preventDefault();
            import('./clipboard.js').then(({ copySelectedNodes }) => {
                copySelectedNodes();
            });
        }
        
        // Cut (Ctrl+X or Cmd+X)
        if ((e.ctrlKey || e.metaKey) && e.key === 'x' && !isEditingInput) {
            e.preventDefault();
            import('./clipboard.js').then(({ cutSelectedNodes }) => {
                cutSelectedNodes();
            });
            import('./history.js').then(({ saveState }) => {
                saveState('cut nodes');
            });
        }
        
        // Paste (Ctrl+V or Cmd+V)
        if ((e.ctrlKey || e.metaKey) && e.key === 'v' && !isEditingInput) {
            e.preventDefault();
            import('./clipboard.js').then(({ pasteNodes }) => {
                pasteNodes();
            });
            import('./history.js').then(({ saveState }) => {
                saveState('paste nodes');
            });
        }
        
        // Undo (Ctrl+Z or Cmd+Z)
        if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey && !isEditingInput) {
            e.preventDefault();
            import('./history.js').then(({ undo }) => {
                undo();
            });
        }
        
        // Redo (Ctrl+Y or Cmd+Shift+Z)
        if (((e.ctrlKey && e.key === 'y') || (e.metaKey && e.shiftKey && e.key === 'z')) && !isEditingInput) {
            e.preventDefault();
            import('./history.js').then(({ redo }) => {
                redo();
            });
        }
    });
    
    setupSelectionBox();
}

function setupSidePanelGrabs() {
    const leftPanel = document.getElementById('left-palette');
    const leftGrab = document.getElementById('left-palette-grab');
    const rightPanel = document.getElementById('right-sidebar');
    const rightGrab = document.getElementById('right-sidebar-grab');

    setupOneSidePanelGrab({
        panel: leftPanel,
        grab: leftGrab,
        side: 'left',
        minWidth: 180,
        maxWidth: 600,
        collapsedWidth: 18,
        storageKey: 'pynode.leftPalette'
    });

    setupOneSidePanelGrab({
        panel: rightPanel,
        grab: rightGrab,
        side: 'right',
        minWidth: 240,
        maxWidth: 700,
        collapsedWidth: 18,
        storageKey: 'pynode.rightSidebar'
    });
}

function setupOneSidePanelGrab({ panel, grab, side, minWidth, maxWidth, collapsedWidth, storageKey }) {
    if (!panel || !grab) return;

    const toggleBtn = grab.querySelector('.panel-toggle-btn');

    const widthKey = `${storageKey}.width`;
    const collapsedKey = `${storageKey}.collapsed`;

    const applyCollapsed = (collapsed) => {
        if (collapsed) {
            panel.classList.add('collapsed');
            panel.style.width = `${collapsedWidth}px`;
        } else {
            panel.classList.remove('collapsed');
            const savedWidth = parseInt(localStorage.getItem(widthKey) || '', 10);
            if (!Number.isNaN(savedWidth)) {
                panel.style.width = `${savedWidth}px`;
            }
        }
        localStorage.setItem(collapsedKey, collapsed ? '1' : '0');
        updateToggleIcon();
    };

    const updateToggleIcon = () => {
        if (!toggleBtn) return;
        const isCollapsed = panel.classList.contains('collapsed');
        if (side === 'left') {
            // Left panel: expanded shows '<' (collapse left), collapsed shows '>' (expand right)
            toggleBtn.textContent = isCollapsed ? '>' : '<';
        } else {
            // Right panel: expanded shows '>' (collapse right), collapsed shows '<' (expand left)
            toggleBtn.textContent = isCollapsed ? '<' : '>';
        }
    };

    // Initial state
    const savedCollapsed = localStorage.getItem(collapsedKey) === '1';
    const savedWidth = parseInt(localStorage.getItem(widthKey) || '', 10);
    if (!Number.isNaN(savedWidth)) {
        panel.style.width = `${savedWidth}px`;
    }
    applyCollapsed(savedCollapsed);

    if (toggleBtn) {
        toggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            applyCollapsed(!panel.classList.contains('collapsed'));
        });
    }

    let isResizing = false;
    let didDrag = false;
    let startX = 0;
    let startWidth = 0;

    const beginResize = (e) => {
        if (toggleBtn && e.target === toggleBtn) return;

        // If currently collapsed and user starts dragging, expand first.
        if (panel.classList.contains('collapsed')) {
            applyCollapsed(false);
        }

        isResizing = true;
        didDrag = false;
        startX = e.clientX;
        startWidth = panel.offsetWidth;
        document.body.style.cursor = 'ew-resize';
        e.preventDefault();
        e.stopPropagation();
    };

    const onMove = (e) => {
        if (!isResizing) return;

        const rawDelta = side === 'left' ? (e.clientX - startX) : (startX - e.clientX);
        if (Math.abs(rawDelta) > 3) didDrag = true;

        const nextWidth = Math.max(minWidth, Math.min(maxWidth, startWidth + rawDelta));
        panel.style.width = `${nextWidth}px`;
    };

    const endResize = () => {
        if (!isResizing) return;
        isResizing = false;
        document.body.style.cursor = '';

        if (didDrag) {
            const w = panel.offsetWidth;
            localStorage.setItem(widthKey, String(w));
        }
    };

    grab.addEventListener('mousedown', beginResize);
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', endResize);
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
    
    // Check if dragging over a connection and highlight it (canvas coords, zoom-aware)
    const canvasPoint = clientToCanvas(e.clientX, e.clientY);

    const hoveredConnection = getConnectionAtPoint(canvasPoint.x, canvasPoint.y, 15 / getZoom());
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
    
    // Drop position in canvas coordinates (zoom-aware). The drag offset is the
    // grab point within the palette item in client px, so subtract it in
    // client space before converting.
    const canvasPoint = clientToCanvas(e.clientX - offsetX, e.clientY - offsetY);
    const x = canvasPoint.x;
    const y = canvasPoint.y;

    const newNodeId = createNode(nodeType, x, y);

    if (newNodeId) {
        // Drop focus out of the palette search (or any other input) so keyboard
        // shortcuts like Delete work immediately on the new node.
        const activeEl = document.activeElement;
        if (activeEl && activeEl !== document.body && typeof activeEl.blur === 'function') {
            activeEl.blur();
        }

        // Select the freshly dropped node so it can be deleted/moved right away.
        selectNode(newNodeId, false);

        // Snap the new node so input port 0 aligns to the grid.
        setTimeout(() => {
            snapNodeToGrid(newNodeId);
        }, 0);
    }
    
    // If dropped on a connection, insert the node into it
    if (connectionToInsertInto && newNodeId) {
        // Small delay to ensure node is fully rendered
        setTimeout(() => {
            insertNodeIntoConnection(newNodeId, connectionToInsertInto);
        }, 50);
    }
}

// The selection box is an HTML overlay on document.body and works entirely in
// CLIENT coordinates: the box rect and each node's getBoundingClientRect()
// are compared in the same (zoomed) client space, so hit-testing stays
// correct at every zoom level without conversion.
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
            
            // If selection box is very small (like a click), check for connection using distance
            const isSmallBox = boxRect.width < 50 && boxRect.height < 50;
            
            if (isSmallBox) {
                // Use proper distance-based connection detection instead of bounding box
                const centerX = boxRect.left + boxRect.width / 2;
                const centerY = boxRect.top + boxRect.height / 2;
                
                // Transform to canvas (SVG) coordinates, zoom-aware
                const canvasPoint = clientToCanvas(centerX, centerY);

                import('./connections.js').then(({ getConnectionAtPoint, selectConnection }) => {
                    const foundConnection = getConnectionAtPoint(canvasPoint.x, canvasPoint.y, 20 / getZoom());
                    
                    if (foundConnection) {
                        console.log('Found connection via distance check:', foundConnection);
                        selectConnection(foundConnection.source, foundConnection.target, foundConnection.sourceOutput);
                        
                        // Prevent canvas click from deselecting immediately
                        state.justSelectedConnection = true;
                        setTimeout(() => {
                            state.justSelectedConnection = false;
                        }, 100);
                    }
                });
            }
            
            state.selectionBox.remove();
            state.selectionBox = null;
            state.selectionStart = null;
        }
    });
}

// Middle-mouse panning works in scroll/client px (1 scroll px == 1 client px
// regardless of zoom), so no canvas-coordinate conversion is needed here.
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
        if (newWidth >= 380 && newWidth <= 800) {
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
