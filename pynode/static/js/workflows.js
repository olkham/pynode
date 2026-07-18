// Multi-workflow tab management
import { API_BASE } from './config.js';
import { state, setModified, setWorkflowStopped, clearChangeTracking, saveActiveWorkflowToCache, restoreWorkflowFromCache } from './state.js';
import { renderNode } from './nodes.js';
import { updateConnections } from './connections.js';
import { showToast } from './ui-utils.js';
import { deselectAllNodes } from './selection.js';
import { loadWorkflowData, enrichNodeWithTypeInfo } from './workflow.js';
import { refilterDebugByWorkflow, populateDebugFlowFilterOptions } from './debug.js';

/**
 * Initialize workflow tabs from the server.
 */
export async function initWorkflowTabs() {
    try {
        const response = await fetch(`${API_BASE}/workflows`);
        const workflows = await response.json();
        
        state.workflows.clear();
        let activeId = null;

        workflows.forEach(wf => {
            state.workflows.set(wf.id, {
                name: wf.name,
                enabled: wf.enabled,
                nodeCount: wf.nodeCount,
                // Live run state of this flow's deployed engine, straight
                // from the backend (authoritative - see list_workflows).
                // Drives both the tab's run-state dot and, for the active
                // flow, the Deploy button's red "stopped" styling.
                running: !!wf.running
            });
            if (wf.active) activeId = wf.id;
        });

        if (!activeId && state.workflows.size > 0) {
            activeId = state.workflows.keys().next().value;
        }

        state.activeWorkflowId = activeId;
        renderTabs();
        // Restore the transient "stopped" indicator across page reloads,
        // scoped to whichever flow is actually active.
        syncDeployButtonToActiveWorkflow();
    } catch (error) {
        console.error('Failed to load workflows:', error);
    }
}

/**
 * Sync the Deploy button's red "stopped" styling to the CURRENTLY ACTIVE
 * workflow's own run state, instead of a stale global flag left over from
 * whichever flow was active when it was last set. Call this any time the
 * active workflow changes (tab switch, initial load) or its meta.running
 * may have changed (workflow enabled/disabled toggle).
 *
 * A disabled flow is intentionally NOT shown as "stopped": that's a
 * distinct, deliberate state already conveyed by the tab's dimmed/italic
 * "disabled" styling and its own dot color, not an unexpected halt.
 */
export function syncDeployButtonToActiveWorkflow() {
    const meta = state.workflows.get(state.activeWorkflowId);
    setWorkflowStopped(!!meta && meta.enabled && meta.running === false);
}

/**
 * Record that the ACTIVE flow's deployed engine now matches its 'enabled'
 * flag - true after a successful deploy (modified or full) or restart,
 * which all start an enabled flow's engine (and leave a disabled one
 * alone). Call after those actions succeed; refreshes the tab dot and the
 * Deploy button to match.
 */
export function refreshActiveWorkflowRunState() {
    const meta = state.workflows.get(state.activeWorkflowId);
    if (meta) meta.running = meta.enabled;
    syncDeployButtonToActiveWorkflow();
    renderTabs();
}

/**
 * Record that the ACTIVE flow's deployed engine is no longer running -
 * true after a successful scoped Stop, regardless of the flow's enabled
 * flag. Refreshes the tab dot and the Deploy button to match.
 */
export function markActiveWorkflowStopped() {
    const meta = state.workflows.get(state.activeWorkflowId);
    if (meta) meta.running = false;
    syncDeployButtonToActiveWorkflow();
    renderTabs();
}

/**
 * Render the workflow tab bar.
 */
export function renderTabs() {
    const container = document.getElementById('workflow-tabs');
    if (!container) return;
    
    // Remove existing tabs (but keep the + button)
    const addBtn = document.getElementById('add-workflow-btn');
    container.querySelectorAll('.workflow-tab').forEach(el => el.remove());
    
    state.workflows.forEach((meta, wid) => {
        const tab = document.createElement('button');
        tab.className = 'workflow-tab';
        if (wid === state.activeWorkflowId) tab.classList.add('active');
        if (!meta.enabled) tab.classList.add('disabled');
        tab.dataset.workflowId = wid;

        // Run-state dot: green while the flow's deployed engine is
        // running, red when it's enabled but stopped (mirrors the Deploy
        // button's red "stopped" styling), dim grey when the flow is
        // disabled (a deliberate, distinct state - not an unexpected halt).
        const statusDot = document.createElement('span');
        statusDot.className = 'tab-status-dot';
        if (!meta.enabled) {
            statusDot.classList.add('tab-status-dot-disabled');
            statusDot.title = 'Disabled';
        } else if (meta.running) {
            statusDot.classList.add('tab-status-dot-running');
            statusDot.title = 'Running';
        } else {
            statusDot.classList.add('tab-status-dot-stopped');
            statusDot.title = 'Stopped';
        }
        tab.appendChild(statusDot);

        const nameSpan = document.createElement('span');
        nameSpan.className = 'tab-name';
        nameSpan.textContent = meta.name;
        tab.appendChild(nameSpan);

        // Single click: switch to workflow (if not active) or open properties (if active)
        tab.addEventListener('click', () => {
            if (wid === state.activeWorkflowId) {
                // Already active - open properties panel for workflow editing
                showWorkflowProperties(wid);
            } else {
                switchWorkflow(wid);
            }
        });

        // Double click: open the properties panel for this workflow (rename
        // and delete both live there now - see showWorkflowProperties).
        tab.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            showWorkflowProperties(wid);
        });

        container.insertBefore(tab, addBtn);
    });

    // Keep the debug panel's flow-scope <select> in sync with the current set
    // of flows (adds/removes/renames), preserving the user's selection.
    populateDebugFlowFilterOptions();

    // If the workflow properties panel is currently open, keep its read-only
    // status line (Running/Stopped/Disabled) in sync - renderTabs() is
    // already called after every meta.running/meta.enabled mutation, so
    // hooking in here covers deploy/stop/restart/switch/enable-toggle
    // without duplicating that logic at each call site.
    refreshWorkflowPropertiesStatus();
}

/**
 * Switch to a different workflow tab.
 */
export async function switchWorkflow(workflowId) {
    if (workflowId === state.activeWorkflowId) return;
    if (!state.workflows.has(workflowId)) return;
    
    // Save current workflow state to cache
    saveActiveWorkflowToCache();
    
    // Clear current canvas
    deselectAllNodes();
    document.getElementById('nodes-container').innerHTML = '';
    document.getElementById('connections').innerHTML = '';
    
    // Set new active workflow
    state.activeWorkflowId = workflowId;

    // Reflect THIS flow's own run state on the Deploy button (red/"stopped"
    // or not) instead of leaving whatever the previously-active flow left
    // behind. Must happen before setModified() below, which also touches
    // the Deploy button and would otherwise read the stale flag.
    syncDeployButtonToActiveWorkflow();

    // Re-scope the debug panel to the newly-active flow. The message
    // buffer itself is untouched - this only hides/shows existing messages
    // (in "Current flow" mode) so switching back later reveals them again.
    refilterDebugByWorkflow();

    // Tell the server about the active workflow
    fetch(`${API_BASE}/workflows/active`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflowId })
    }).catch(err => console.error('Failed to set active workflow:', err));
    
    // Try to restore from cache first
    if (restoreWorkflowFromCache(workflowId)) {
        // Re-render from cached state
        state.nodes.forEach(nodeData => renderNode(nodeData));
        updateConnections();
        setModified(state.isModified);
    } else {
        // Load from server
        await loadWorkflowData(workflowId);
    }
    
    // Close properties panel when switching
    const propertiesPanel = document.getElementById('properties-panel-container');
    if (propertiesPanel) propertiesPanel.classList.add('hidden');
    
    // Clear history for the new tab
    import('./history.js').then(({ clearHistory }) => {
        clearHistory();
    });
    
    renderTabs();
}

/**
 * Create a new workflow.
 */
export async function createNewWorkflow(name) {
    try {
        const response = await fetch(`${API_BASE}/workflows`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name || 'New Workflow' })
        });
        
        if (!response.ok) throw new Error('Failed to create workflow');
        
        const wf = await response.json();
        state.workflows.set(wf.id, {
            name: wf.name,
            enabled: wf.enabled,
            nodeCount: 0,
            // create_workflow always starts the deployed engine immediately
            // (see pynode/api/workflows.py create_workflow).
            running: true
        });
        
        // Switch to the new workflow
        await switchWorkflow(wf.id);
        showToast(`Created workflow: ${wf.name}`);
    } catch (error) {
        console.error('Failed to create workflow:', error);
        showToast('Failed to create workflow');
    }
}

/**
 * Delete a workflow.
 */
async function deleteWorkflow(workflowId) {
    if (state.workflows.size <= 1) {
        showToast('Cannot delete the last workflow');
        return;
    }
    
    const name = state.workflows.get(workflowId)?.name || 'this workflow';
    if (!confirm(`Delete workflow "${name}"?`)) return;
    
    try {
        const response = await fetch(`${API_BASE}/workflows/${workflowId}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) throw new Error('Failed to delete workflow');
        
        const result = await response.json();
        
        // Remove from local state
        state.workflows.delete(workflowId);
        state.workflowCache.delete(workflowId);
        
        // If we deleted the active workflow, switch to what server says
        if (workflowId === state.activeWorkflowId) {
            state.activeWorkflowId = result.activeWorkflow;
            syncDeployButtonToActiveWorkflow();
            refilterDebugByWorkflow();
            // Clear canvas and load the new active workflow
            document.getElementById('nodes-container').innerHTML = '';
            document.getElementById('connections').innerHTML = '';
            await loadWorkflowData(state.activeWorkflowId);
        }
        
        renderTabs();
        showToast(`Deleted workflow: ${name}`);

        // The workflow whose properties were showing no longer exists (the
        // Delete button only ever appears inside its own properties panel -
        // see showWorkflowProperties). Close the panel rather than leaving
        // it displaying a stale, deleted workflow's name/status.
        const propertiesPanel = document.getElementById('properties-panel-container');
        if (propertiesPanel) propertiesPanel.classList.add('hidden');
    } catch (error) {
        console.error('Failed to delete workflow:', error);
        showToast('Failed to delete workflow');
    }
}

/**
 * Derive the read-only run-state text shown in the workflow properties
 * panel from the same per-flow meta that drives the tab's status dot.
 */
function computeWorkflowStatusText(meta) {
    if (!meta.enabled) return 'Disabled';
    return meta.running ? 'Running' : 'Stopped (enabled — start via Deploy)';
}

/**
 * If the workflow properties panel is currently open, refresh its status
 * line in place from the latest meta. Safe to call anytime (e.g. from
 * renderTabs(), which already runs after every meta.running/meta.enabled
 * mutation) - it no-ops when the panel is hidden or showing node properties.
 */
function refreshWorkflowPropertiesStatus() {
    const container = document.getElementById('properties-panel-container');
    if (!container || container.classList.contains('hidden')) return;

    const wfProps = document.querySelector('.workflow-properties');
    const statusEl = document.getElementById('wf-prop-status');
    if (!wfProps || !statusEl) return;

    const workflowId = wfProps.dataset.workflowId;
    const meta = state.workflows.get(workflowId);
    if (meta) statusEl.textContent = computeWorkflowStatusText(meta);
}

/**
 * Show workflow properties in the properties panel: name (rename), enabled
 * toggle, a read-only run-state line, and workflow deletion - the tabs
 * themselves only switch/open this panel now (see renderTabs()).
 */
function showWorkflowProperties(workflowId) {
    const meta = state.workflows.get(workflowId);
    if (!meta) return;

    const panel = document.getElementById('properties-panel');
    const container = document.getElementById('properties-panel-container');

    // Deselect any selected node
    deselectAllNodes();

    panel.innerHTML = `
        <div class="workflow-properties" data-workflow-id="${workflowId}">
            <div class="property-group">
                <label class="property-label">Workflow Name</label>
                <input type="text" class="property-input" id="wf-prop-name" value="${meta.name}" />
            </div>
            <div class="property-group">
                <label class="property-label">
                    <input type="checkbox" id="wf-prop-enabled" ${meta.enabled ? 'checked' : ''} />
                    Enabled
                </label>
                <span class="property-hint">Disabled workflows won't run when deployed</span>
            </div>
            <div class="property-group">
                <label class="property-label">Status</label>
                <div class="property-status-text" id="wf-prop-status">${computeWorkflowStatusText(meta)}</div>
            </div>
            <div class="property-group workflow-danger-zone">
                <button type="button" class="btn btn-danger" id="wf-prop-delete">Delete Workflow</button>
            </div>
        </div>
    `;

    container.classList.remove('hidden');

    // Wire up change handlers
    const nameInput = document.getElementById('wf-prop-name');
    const applyRename = async () => {
        const newName = nameInput.value.trim();
        if (!newName || newName === meta.name) {
            nameInput.value = meta.name;
            return;
        }
        try {
            const response = await fetch(`${API_BASE}/workflows/${workflowId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newName })
            });
            if (response.ok) {
                const result = await response.json();
                meta.name = result.name;
                nameInput.value = result.name;
                renderTabs();
            } else {
                nameInput.value = meta.name;
            }
        } catch (error) {
            console.error('Failed to update workflow name:', error);
            nameInput.value = meta.name;
        }
    };
    // Apply on blur (covers clicking/tabbing away) and on Enter (which blurs
    // the field, triggering the same handler rather than duplicating it).
    nameInput.addEventListener('blur', applyRename);
    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            nameInput.blur();
        } else if (e.key === 'Escape') {
            nameInput.value = meta.name;
            nameInput.blur();
        }
    });

    const enabledCheckbox = document.getElementById('wf-prop-enabled');
    enabledCheckbox.addEventListener('change', async () => {
        try {
            const response = await fetch(`${API_BASE}/workflows/${workflowId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: enabledCheckbox.checked })
            });
            if (response.ok) {
                const result = await response.json();
                meta.enabled = result.enabled;
                // The backend synchronously starts/stops the deployed
                // engine to match 'enabled' (see update_workflow), so the
                // flow's running state now mirrors it too.
                meta.running = result.enabled;
                renderTabs();
                if (workflowId === state.activeWorkflowId) {
                    syncDeployButtonToActiveWorkflow();
                }
            } else {
                enabledCheckbox.checked = meta.enabled;
            }
        } catch (error) {
            console.error('Failed to update workflow enabled state:', error);
            enabledCheckbox.checked = meta.enabled;
        }
    });

    const deleteBtn = document.getElementById('wf-prop-delete');
    deleteBtn.addEventListener('click', () => {
        deleteWorkflow(workflowId);
    });
}
