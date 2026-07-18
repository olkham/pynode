// Workflow import/export and deployment
import { API_BASE } from './config.js';
import { state, setModified, clearAllNodeModifiedIndicators, clearChangeTracking, hasChanges, getNodeType, markNodeAdded, markConnectionAdded } from './state.js';
import { renderNode } from './nodes.js';
import { updateConnections } from './connections.js';
import { showToast } from './ui-utils.js';
import { deselectAllNodes } from './selection.js';

// Deploy/stop/restart all change the ACTIVE flow's run state, which
// workflows.js tracks per-workflow (meta.running, feeding both the tab's
// run-state dot and the Deploy button's red "stopped" styling). Lazy-import
// to avoid a circular top-level import, since workflows.js itself imports
// from this module.
function syncRunStateAfterDeployOrRestart() {
    import('./workflows.js').then(
        (workflowsModule) => workflowsModule.refreshActiveWorkflowRunState());
}
function syncRunStateAfterStop() {
    import('./workflows.js').then(
        (workflowsModule) => workflowsModule.markActiveWorkflowStopped());
}

// Helper function to enrich node data with type information
export function enrichNodeWithTypeInfo(nodeData) {
    const nodeType = getNodeType(nodeData.type);
    if (nodeType) {
        nodeData.color = nodeType.color;
        nodeData.borderColor = nodeType.borderColor;
        nodeData.textColor = nodeType.textColor;
        nodeData.icon = nodeType.icon;
        nodeData.inputCount = nodeType.inputCount;
        nodeData.outputCount = nodeType.outputCount;
        nodeData.isUnknownNode = false;
        
        // Handle dynamic output counts (e.g., SwitchNode)
        if (nodeData.type === 'SwitchNode' && nodeData.config && nodeData.config.rules) {
            nodeData.outputCount = Math.max(1, nodeData.config.rules.length);
        }
    } else {
        // Unknown node type - mark as placeholder
        nodeData.isUnknownNode = true;
        nodeData.color = '#3d3d3d';
        nodeData.borderColor = '#ff6b6b';
        nodeData.textColor = '#999';
        nodeData.icon = '❓';
        // Preserve input/output counts if provided in the workflow data
        nodeData.inputCount = nodeData.inputCount || 1;
        nodeData.outputCount = nodeData.outputCount || 1;
        // Force disabled state
        nodeData.enabled = false;
        console.warn(`Unknown node type: ${nodeData.type} - rendering as placeholder`);
    }
    return nodeData;
}

export async function loadWorkflow() {
    try {
        // First load the workflow list to set up tabs
        const { initWorkflowTabs } = await import('./workflows.js');
        await initWorkflowTabs();
        
        // Then load the active workflow data
        if (state.activeWorkflowId) {
            await loadWorkflowData(state.activeWorkflowId);
        }
    } catch (error) {
        console.error('Failed to load workflow:', error);
    }
}

/**
 * Load workflow data for a specific workflow from the server and render it.
 */
export async function loadWorkflowData(workflowId) {
    try {
        const response = await fetch(`${API_BASE}/workflow?workflow=${workflowId}`);
        const workflow = await response.json();
        
        state.nodes.clear();
        state.connections = [];
        document.getElementById('nodes-container').innerHTML = '';
        document.getElementById('connections').innerHTML = '';
        
        // First, process all node data with async operations
        const nodePromises = workflow.nodes.map(async (nodeData) => {
            nodeData.x = nodeData.x !== undefined ? nodeData.x : 100;
            nodeData.y = nodeData.y !== undefined ? nodeData.y : 100;
            
            enrichNodeWithTypeInfo(nodeData);
            
            if (nodeData.type === 'GateNode') {
                try {
                    const enabledResponse = await fetch(`${API_BASE}/nodes/${nodeData.id}/enabled`);
                    const enabledData = await enabledResponse.json();
                    nodeData.enabled = enabledData.enabled;
                } catch (error) {
                    nodeData.enabled = true;
                }
            }
            
            if (nodeData.type === 'DebugNode') {
                try {
                    const enabledResponse = await fetch(`${API_BASE}/nodes/${nodeData.id}/enabled`);
                    const enabledData = await enabledResponse.json();
                    nodeData.enabled = enabledData.enabled;
                } catch (error) {
                    nodeData.enabled = true;
                }
            }
            
            return nodeData;
        });
        
        // Wait for all async operations to complete
        const processedNodes = await Promise.all(nodePromises);
        
        // Now render all nodes synchronously
        processedNodes.forEach(nodeData => {
            state.nodes.set(nodeData.id, nodeData);
            renderNode(nodeData);
        });
        
        // Load connections into state
        workflow.connections.forEach(conn => {
            state.connections.push(conn);
        });
        
        // Render connections immediately after nodes are in DOM
        updateConnections();
        
        // Clear history after loading workflow
        import('./history.js').then(({ clearHistory }) => {
            clearHistory();
        });
        
        // Clear change tracking since we just loaded from server
        clearChangeTracking();
        setModified(false);
    } catch (error) {
        console.error('Failed to load workflow:', error);
    }
}

export async function deployWorkflow() {
    try {
        // Build list of changed nodes
        const modifiedNodesList = [];
        const addedNodesList = [];
        const deletedNodeIds = Array.from(state.deletedNodes);
        
        // Collect modified nodes (config/property changes)
        state.modifiedNodes.forEach(nodeId => {
            const nodeData = state.nodes.get(nodeId);
            if (nodeData) {
                modifiedNodesList.push({
                    id: nodeData.id,
                    type: nodeData.type,
                    name: nodeData.name,
                    config: nodeData.config,
                    enabled: nodeData.enabled !== undefined ? nodeData.enabled : true,
                    x: nodeData.x,
                    y: nodeData.y
                });
            }
        });
        
        // Collect added nodes
        state.addedNodes.forEach(nodeId => {
            const nodeData = state.nodes.get(nodeId);
            if (nodeData) {
                addedNodesList.push({
                    id: nodeData.id,
                    type: nodeData.type,
                    name: nodeData.name,
                    config: nodeData.config,
                    enabled: nodeData.enabled !== undefined ? nodeData.enabled : true,
                    x: nodeData.x,
                    y: nodeData.y
                });
            }
        });
        
        const changes = {
            workflowId: state.activeWorkflowId,
            modifiedNodes: modifiedNodesList,
            addedNodes: addedNodesList,
            deletedNodes: deletedNodeIds,
            addedConnections: state.addedConnections,
            deletedConnections: state.deletedConnections
        };
        
        // Use incremental deploy endpoint
        const response = await fetch(`${API_BASE}/workflow/deploy-changes`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(changes)
        });
        
        if (response.ok) {
            const result = await response.json();
            clearAllNodeModifiedIndicators();
            clearChangeTracking();
            const wasStopped = state.workflowStopped;
            setModified(false);
            syncRunStateAfterDeployOrRestart();

            // Show appropriate message based on what was deployed
            const changedCount = result.nodesRestarted || 0;
            if (changedCount === 0) {
                showToast(wasStopped ? 'Workflow processing resumed' : 'No changes to deploy');
            } else if (changedCount === 1) {
                showToast('Deployed 1 changed node');
            } else {
                showToast(`Deployed ${changedCount} changed nodes`);
            }
        } else {
            throw new Error('Failed to deploy workflow');
        }
    } catch (error) {
        console.error('Failed to deploy workflow:', error);
        showToast('Failed to deploy workflow');
    }
}

export async function deployWorkflowFull() {
    try {
        const nodes = [];
        state.nodes.forEach((nodeData) => {
            const nodeExport = {
                id: nodeData.id,
                type: nodeData.type,
                name: nodeData.name,
                config: nodeData.config,
                enabled: nodeData.enabled !== undefined ? nodeData.enabled : true,
                x: nodeData.x,
                y: nodeData.y
            };
            // Include input/output counts for unknown nodes to preserve them
            if (nodeData.isUnknownNode) {
                nodeExport.inputCount = nodeData.inputCount;
                nodeExport.outputCount = nodeData.outputCount;
            }
            nodes.push(nodeExport);
        });
        
        const workflow = {
            nodes: nodes,
            connections: state.connections
        };
        
        const response = await fetch(`${API_BASE}/workflow?workflow=${state.activeWorkflowId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(workflow)
        });
        
        if (response.ok) {
            clearAllNodeModifiedIndicators();
            clearChangeTracking();
            setModified(false);
            syncRunStateAfterDeployOrRestart();
            showToast('Full workflow deployed!');
        } else {
            throw new Error('Failed to deploy workflow');
        }
    } catch (error) {
        console.error('Failed to deploy workflow:', error);
        showToast('Failed to deploy workflow');
    }
}

/**
 * Restart the CURRENTLY ACTIVE flow's deployed engine without a full
 * redeploy. Scoped to this one flow (via ?workflow=) so it does not disturb
 * other open tabs' processing.
 */
export async function restartWorkflow() {
    try {
        const response = await fetch(
            `${API_BASE}/workflow/restart?workflow=${state.activeWorkflowId}`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' } }
        );

        if (response.ok) {
            // Restart starts this flow again (if enabled), so any transient
            // stop is over.
            syncRunStateAfterDeployOrRestart();
            const name = state.workflows.get(state.activeWorkflowId)?.name;
            showToast(name ? `"${name}" restarted!` : 'Workflow restarted!');
        } else {
            throw new Error('Failed to restart workflow');
        }
    } catch (error) {
        console.error('Failed to restart workflow:', error);
        showToast('Failed to restart workflow');
    }
}

/**
 * Transiently stop the CURRENTLY ACTIVE flow's deployed processing ("Stop"
 * in the deploy menu). Scoped to this one flow (via ?workflow=) so other
 * open tabs keep running. The flow stays enabled and nothing is persisted;
 * selecting Deploy (modified or full) or Restart starts it again.
 */
export async function stopWorkflow() {
    try {
        const response = await fetch(
            `${API_BASE}/workflow/stop?workflow=${state.activeWorkflowId}`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' } }
        );

        if (response.ok) {
            const result = await response.json();
            syncRunStateAfterStop();
            const name = state.workflows.get(state.activeWorkflowId)?.name;
            const label = name ? `"${name}"` : 'Flow';
            const wasRunning = (result.stopped || 0) > 0;
            showToast(wasRunning
                ? `${label} stopped - Deploy to start again`
                : `${label} already stopped`);
        } else {
            throw new Error('Failed to stop workflow');
        }
    } catch (error) {
        console.error('Failed to stop workflow:', error);
        showToast('Failed to stop workflow');
    }
}

export function clearWorkflow() {
    if (!confirm('Clear all nodes and connections?')) return;
    
    state.nodes.clear();
    state.connections = [];
    
    document.getElementById('nodes-container').innerHTML = '';
    document.getElementById('connections').innerHTML = '';
    
    deselectAllNodes();

    // Clear history when clearing workflow
    import('./history.js').then(({ clearHistory }) => {
        clearHistory();
    });

    // Empty canvas -> redraw the minimap
    import('./minimap.js').then(({ refreshMinimap }) => {
        refreshMinimap();
    });

    setModified(true);
}

export function exportWorkflow() {
    try {
        const nodes = [];
        state.nodes.forEach((nodeData) => {
            const nodeExport = {
                id: nodeData.id,
                type: nodeData.type,
                name: nodeData.name,
                config: nodeData.config,
                x: nodeData.x,
                y: nodeData.y
            };
            // Include input/output counts for unknown nodes to preserve them
            if (nodeData.isUnknownNode) {
                nodeExport.inputCount = nodeData.inputCount;
                nodeExport.outputCount = nodeData.outputCount;
            }
            nodes.push(nodeExport);
        });
        
        const workflow = {
            nodes: nodes,
            connections: state.connections
        };
        
        const dataStr = JSON.stringify(workflow, null, 2);
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(dataBlob);
        
        const link = document.createElement('a');
        link.href = url;
        link.download = 'workflow.json';
        link.click();
    } catch (error) {
        console.error('Failed to export workflow:', error);
    }
}

export function exportSelected() {
    try {
        const nodes = [];
        // If nothing selected, fallback to exporting full workflow
        if (!state.selectedNodes || state.selectedNodes.size === 0) {
            return exportWorkflow();
        }

        const selectedSet = new Set(Array.from(state.selectedNodes));

        state.nodes.forEach((nodeData) => {
            if (selectedSet.has(nodeData.id)) {
                const nodeExport = {
                    id: nodeData.id,
                    type: nodeData.type,
                    name: nodeData.name,
                    config: nodeData.config,
                    x: nodeData.x,
                    y: nodeData.y
                };
                // Include input/output counts for unknown nodes to preserve them
                if (nodeData.isUnknownNode) {
                    nodeExport.inputCount = nodeData.inputCount;
                    nodeExport.outputCount = nodeData.outputCount;
                }
                nodes.push(nodeExport);
            }
        });

        // Include only connections where both ends are selected
        const connections = state.connections.filter(conn => selectedSet.has(conn.source) && selectedSet.has(conn.target));

        const workflow = { nodes, connections };

        const dataStr = JSON.stringify(workflow, null, 2);
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(dataBlob);

        const link = document.createElement('a');
        link.href = url;
        link.download = 'workflow-selected.json';
        link.click();
    } catch (error) {
        console.error('Failed to export selected nodes:', error);
    }
}

// Load a parsed workflow object into a brand-new workflow tab. Shared by
// file import and example loading so both behave identically.
export async function loadWorkflowObject(workflow, name) {
    if (!workflow || !Array.isArray(workflow.nodes)) {
        throw new Error('Invalid workflow: missing "nodes" array');
    }

    // Import creates a new workflow tab
    const { createNewWorkflow } = await import('./workflows.js');
    await createNewWorkflow(name);

    // Now populate the new (now active) workflow with imported data
    state.nodes.clear();
    state.connections = [];
    document.getElementById('nodes-container').innerHTML = '';
    document.getElementById('connections').innerHTML = '';

    workflow.nodes.forEach(nodeData => {
        enrichNodeWithTypeInfo(nodeData);
        state.nodes.set(nodeData.id, nodeData);
        renderNode(nodeData);
        // Register with change tracking: the default "Deploy modified" mode
        // sends only tracked changes, so without this the backend never
        // learns about the imported nodes and node actions 404.
        markNodeAdded(nodeData.id);
    });

    (workflow.connections || []).forEach(conn => {
        state.connections.push(conn);
        markConnectionAdded(conn);
    });

    // Render all connections after nodes are in DOM
    updateConnections();

    // Clear history after importing workflow
    import('./history.js').then(({ clearHistory }) => {
        clearHistory();
    });

    setModified(true);
}

export function importWorkflow() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/json';

    input.onchange = async (e) => {
        const file = e.target.files[0];
        const text = await file.text();

        try {
            const workflow = JSON.parse(text);
            // Derive name from filename (strip .json)
            const name = file.name.replace(/\.json$/i, '');
            await loadWorkflowObject(workflow, name);
            showToast('Workflow imported into new tab. Deploy to activate.');
        } catch (error) {
            console.error('Failed to import workflow:', error);
            showToast('Failed to import workflow');
        }
    };

    input.click();
}

// Fetch the bundled example manifest (served from static/examples/).
export async function fetchExamples() {
    const response = await fetch('examples/manifest.json', { cache: 'no-cache' });
    if (!response.ok) {
        throw new Error(`Failed to load examples manifest (${response.status})`);
    }
    const data = await response.json();
    return data.examples || [];
}

// Load one bundled example workflow (by manifest entry) into a new tab.
export async function loadExampleWorkflow(example) {
    try {
        const response = await fetch(`examples/${example.file}`, { cache: 'no-cache' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const workflow = await response.json();
        await loadWorkflowObject(workflow, example.title || example.id);
        showToast(`Loaded example "${example.title || example.id}". Deploy to activate.`);
    } catch (error) {
        console.error('Failed to load example workflow:', error);
        showToast('Failed to load example');
    }
}
