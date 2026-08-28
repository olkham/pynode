// Properties panel
//
// A generic engine over the property schema each node class declares. The
// built-in types below are the ones many nodes share; anything else is looked
// up in the node-UI registry, where a node's own module registered an editor
// for it (see js/node-ui/README.md). Node-specific rendering does not live
// here.
import { state, markNodeModified, setModified, getNodeType } from './state.js';
import { API_BASE } from './config.js';
import { updateNodeOutputCount, updateNodeInputCount } from './nodes.js';
import { updateConnections } from './connections.js';
import { showToast } from './ui-utils.js';
import { getPropertyEditor } from './node-ui/registry.js';
import { createPropertyContext } from './node-ui/context.js';
import { esc as escapeHtml } from './node-ui/dom.js';

// Helper function to check if property should be shown
function shouldShowProperty(showIf, config) {
    for (const [key, value] of Object.entries(showIf)) {
        const configValue = config[key];
        
        if (Array.isArray(value)) {
            // Check if config value is in the array
            if (!value.includes(configValue)) {
                return false;
            }
        } else {
            // Check if config value matches
            if (configValue !== value) {
                return false;
            }
        }
    }
    return true;
}

export function renderProperties(nodeData) {
    const panel = document.getElementById('properties-panel');
    const panelContainer = document.getElementById('properties-panel-container');
    if (panelContainer) {
        panelContainer.classList.remove('hidden');
    }
    
    const isEnabled = nodeData.enabled !== undefined ? nodeData.enabled : true;

    // Editors registered by node UI modules are mounted as real elements after
    // the panel's HTML lands; each one reserves a slot as the HTML is built.
    destroyMountedEditors();
    const pendingEditors = [];
    
    let html = `
        <div class="property-group">
            <label class="property-label">Name</label>
            <input type="text" class="property-input" value="${escapeHtml(nodeData.name)}"
                   onchange="window.updateNodeProperty('${nodeData.id}', 'name', this.value)">
        </div>
        <div class="property-group property-enabled-row">
            <span class="property-label">Enabled</span>
            <label class="gate-switch">
                <input type="checkbox" ${isEnabled ? 'checked' : ''} 
                       onchange="window.toggleNodeEnabled('${nodeData.id}', this.checked)">
                <span class="gate-slider"></span>
            </label>
        </div>
    `;
    
    const nodeType = getNodeType(nodeData.type);
    if (nodeType && nodeType.properties) {
        nodeType.properties.forEach(prop => {
            // Add property group with conditional visibility
            const shouldShow = !prop.showIf || shouldShowProperty(prop.showIf, nodeData.config);
            
            html += '<div class="property-group"';
            // Add data attribute for dynamic visibility
            if (prop.showIf) {
                html += ` data-show-if='${JSON.stringify(prop.showIf)}'`;
            }
            // Hide initially if condition not met
            if (!shouldShow) {
                html += ' style="display: none;"';
            }
            html += '>';
            
            if (prop.type === 'text') {
                const value = nodeData.config[prop.name] !== undefined ? nodeData.config[prop.name] : (prop.default || '');
                const placeholder = prop.placeholder || prop.default || '';
                html += `
                    <label class="property-label">${prop.label}</label>
                    <input type="text" class="property-input"
                           value="${escapeHtml(value)}"
                           placeholder="${escapeHtml(placeholder)}"
                           onchange="window.updateNodeConfig('${nodeData.id}', '${prop.name}', this.value)">
                `;
            } else if (prop.type === 'password') {
                // Secret-shaped text (Qwen3VLMNode's HuggingFace token). Same
                // storage as 'text'; masked on screen, and kept out of the
                // browser's autofill.
                const value = nodeData.config[prop.name] !== undefined ? nodeData.config[prop.name] : (prop.default || '');
                html += `
                    <label class="property-label">${prop.label}</label>
                    <input type="password" class="property-input"
                           value="${escapeHtml(value)}"
                           placeholder="${escapeHtml(prop.placeholder || '')}"
                           autocomplete="off"
                           onchange="window.updateNodeConfig('${nodeData.id}', '${prop.name}', this.value)">
                `;
            } else if (prop.type === 'number') {
                const value = nodeData.config[prop.name] !== undefined ? nodeData.config[prop.name] : (prop.default || 0);
                html += `
                    <label class="property-label">${prop.label}</label>
                    <input type="number" class="property-input" 
                           value="${escapeHtml(value)}"
                           onchange="window.updateNodeConfig('${nodeData.id}', '${prop.name}', parseFloat(this.value))">
                `;
            } else if (prop.type === 'checkbox') {
                const checked = nodeData.config[prop.name] !== undefined ? nodeData.config[prop.name] : (prop.default || false);
                html += `
                    <label class="property-label">
                        <input type="checkbox" class="property-checkbox" 
                               ${checked ? 'checked' : ''}
                               onchange="window.updateNodeConfig('${nodeData.id}', '${prop.name}', this.checked)">
                        ${prop.label}
                    </label>
                `;
            } else if (prop.type === 'textarea') {
                const value = nodeData.config[prop.name] !== undefined ? nodeData.config[prop.name] : (prop.default || '');
                const placeholder = prop.placeholder || prop.default || '';
                html += `
                    <label class="property-label">${prop.label}</label>
                    <textarea class="property-input property-textarea" 
                              placeholder="${escapeHtml(placeholder)}"
                              onchange="window.updateNodeConfig('${nodeData.id}', '${prop.name}', this.value)">${escapeHtml(value)}</textarea>
                `;
            } else if (prop.type === 'select') {
                html += `
                    <label class="property-label">${prop.label}</label>
                    <select class="property-select"
                            onchange="window.updateNodeConfig('${nodeData.id}', '${prop.name}', this.value); window.updatePropertyVisibility('${nodeData.id}')">
                `;
                prop.options.forEach(option => {
                    const selected = nodeData.config[prop.name] === option.value ? 'selected' : '';
                    html += `<option value="${option.value}" ${selected}>${option.label}</option>`;
                });
                // A saved value not among the current options (e.g. a device
                // from another machine's hardware) would otherwise silently
                // render as the first option while the stale value stays in
                // the config - show it explicitly instead.
                const savedValue = nodeData.config[prop.name];
                if (savedValue !== undefined && savedValue !== '' &&
                    !prop.options.some(option => option.value === savedValue)) {
                    html += `<option value="${escapeHtml(String(savedValue))}" selected>${escapeHtml(String(savedValue))} (saved value - unavailable here)</option>`;
                }
                html += '</select>';
            } else if (prop.type === 'button') {
                html += `
                    <button class="btn btn-primary" onclick="window.triggerNodeAction('${nodeData.id}', '${prop.action}')">${prop.label}</button>
                `;
            } else if (prop.type === 'toggle') {
                // Toggle switch with action - syncs with node's uiComponent toggle
                const stateField = prop.stateField || 'drawingEnabled';  // Default for backward compat
                const isChecked = nodeData[stateField] !== false;  // Default to true if undefined
                html += `
                    <div class="property-toggle-row">
                        <span class="property-label">${prop.label}</span>
                        <label class="gate-switch">
                            <input type="checkbox" 
                                   id="prop-toggle-${nodeData.id}-${prop.name}"
                                   data-state-field="${stateField}"
                                   ${isChecked ? 'checked' : ''}
                                   onchange="window.triggerToggleAction('${nodeData.id}', '${prop.action}', '${stateField}', this.checked)">
                            <span class="gate-slider"></span>
                        </label>
                    </div>
                `;
            } else if (prop.type === 'file') {
                const value = nodeData.config[prop.name] !== undefined ? nodeData.config[prop.name] : (prop.default || '');
                const accept = prop.accept || '';
                const uploadRoute = prop.uploadRoute || '';
                const placeholder = prop.placeholder || 'Select or enter file path...';
                const fileId = `file-${nodeData.id}-${prop.name}`;
                html += `
                    <label class="property-label">${prop.label}</label>
                    <div class="property-file-container">
                        <input type="text" class="property-input property-file-path" 
                               value="${escapeHtml(value)}"
                               placeholder="${escapeHtml(placeholder)}"
                               onchange="window.updateNodeConfig('${nodeData.id}', '${prop.name}', this.value)">
                        <button class="btn btn-secondary property-file-btn" onclick="window.selectFile('${nodeData.id}', '${prop.name}', '${accept}', '${uploadRoute}')">
                            <i class="fas fa-folder-open"></i>
                        </button>
                    </div>
                    <div class="upload-progress-container" id="${fileId}-progress" style="display:none;">
                        <div class="upload-progress-bar">
                            <div class="upload-progress-fill" id="${fileId}-fill"></div>
                        </div>
                        <span class="upload-progress-text" id="${fileId}-text">0%</span>
                    </div>
                `;
            } else if (prop.type === 'multiselect') {
                // Multiselect - allows selecting multiple options with checkboxes
                const selectedValues = nodeData.config[prop.name] || prop.default || [];
                html += `<label class="property-label">${prop.label}</label>`;
                html += `<div class="property-multiselect" data-prop="${prop.name}">`;
                
                prop.options.forEach(option => {
                    const optValue = typeof option === 'object' ? option.value : option;
                    const optLabel = typeof option === 'object' ? option.label : option;
                    const isChecked = Array.isArray(selectedValues) ? selectedValues.includes(optValue) : selectedValues === optValue;
                    
                    html += `
                        <label class="multiselect-option">
                            <input type="checkbox" 
                                   value="${optValue}"
                                   ${isChecked ? 'checked' : ''}
                                   onchange="window.updateMultiselectConfig('${nodeData.id}', '${prop.name}', this)">
                            <span>${optLabel}</span>
                        </label>
                    `;
                });
                
                html += '</div>';
            } else if (prop.type === 'hint') {
                // Static callout, no config value - points the user at help
                // that lives elsewhere (typically a copyable example in the
                // node's Information panel, which users never find on their
                // own). `button` is optional; when set it opens that panel.
                const button = prop.button
                    ? `<button class="btn btn-secondary btn-small property-hint-btn"
                               onclick="window.showInfoPanel()">${prop.button}</button>`
                    : '';
                html += `
                    <div class="property-hint">
                        <span class="property-hint-icon">ℹ️</span>
                        <div class="property-hint-body">
                            <span class="property-hint-text">${prop.label}</span>
                            ${button}
                        </div>
                    </div>
                `;
            } else if (getPropertyEditor(prop.type)) {
                // A node-supplied editor. Reserve an empty slot now; the
                // element is mounted into it after innerHTML lands, below.
                const slotId = `prop-slot-${nodeData.id}-${prop.name}`;
                pendingEditors.push({ slotId, prop });
                html += `<div class="property-editor-slot" id="${slotId}"></div>`;
            } else {
                // Say so, loudly. A property type nothing renders used to
                // produce an empty div - invisible on screen, and how a
                // declared-but-never-implemented type could survive unnoticed.
                console.error(
                    `[node-ui] ${nodeData.type}: no editor registered for property type ` +
                    `'${prop.type}' (property '${prop.name}').`);
                html += `
                    <label class="property-label">${prop.label}</label>
                    <div class="property-missing-editor">
                        No editor registered for property type <code>${escapeHtml(prop.type)}</code>
                    </div>
                `;
            }

            if (prop.help) {
                html += `<small class="property-help">${prop.help}</small>`;
            }
            
            html += '</div>';
        });
    }
    
    panel.innerHTML = html;

    mountPendingEditors(nodeData, pendingEditors);

    // Update property visibility based on current config
    window.updatePropertyVisibility(nodeData.id);
}

// Editors currently on screen, so they can be torn down before the panel is
// replaced and notified when the config changes underneath them.
let mountedEditors = [];

function destroyMountedEditors() {
    for (const { editor, el, ctx } of mountedEditors) {
        try {
            if (editor.destroy) editor.destroy(el, ctx);
        } catch (error) {
            console.error('[node-ui] editor destroy() failed:', error);
        }
    }
    mountedEditors = [];
}

/**
 * Build each node-supplied editor and drop it into the slot reserved for it.
 *
 * One editor throwing must not take the rest of the panel with it, so every
 * call into node-supplied code is guarded.
 */
function mountPendingEditors(nodeData, pending) {
    const deps = {
        updateConfig: updateNodeConfig,
        setOutputCount: updateNodeOutputCount,
        rerender: () => renderProperties(nodeData),
    };

    for (const { slotId, prop } of pending) {
        const slot = document.getElementById(slotId);
        const editor = getPropertyEditor(prop.type);
        if (!slot || !editor) continue;

        const ctx = createPropertyContext({ nodeData, prop, deps });
        let el;
        try {
            el = editor.mount(ctx);
        } catch (error) {
            console.error(`[node-ui] editor for '${prop.type}' failed to mount:`, error);
            slot.textContent = `The editor for '${prop.type}' failed to load.`;
            slot.classList.add('property-missing-editor');
            continue;
        }

        slot.appendChild(el);
        mountedEditors.push({ editor, el, ctx, prop });

        if (editor.ready) {
            // ready() may be async (fetching suggestions, broker lists); a
            // rejection must not break the panel that is already on screen.
            Promise.resolve()
                .then(() => editor.ready(el, ctx))
                .catch(error => console.error(`[node-ui] editor for '${prop.type}' ready() failed:`, error));
        }
    }
}

/**
 * Tell mounted editors that a config key changed, so an editor whose display
 * is derived from another property can re-sync without a full re-render (the
 * Function node's example dropdown switching to "Custom" when the code is
 * edited by hand).
 */
function notifyEditorsOfConfigChange(nodeId, key, value) {
    for (const { editor, el, ctx } of mountedEditors) {
        if (!editor.onConfigChange || ctx.nodeId !== nodeId) continue;
        try {
            editor.onConfigChange(el, key, value, ctx);
        } catch (error) {
            console.error('[node-ui] editor onConfigChange() failed:', error);
        }
    }
}

/**
 * Populate the <datalist> for every 'link-channel' property rendered on this
 * node: union of server-known channels (GET /api/link-channels, which scans
 * every workflow's working engine) and channels already present on
 * LinkInNode/LinkOutNode configs in the current client-side editor state
 * (state.nodes) - deduped and sorted. Free-text entry still works; this only
 * adds suggestions.
 */
export function updateNodeProperty(nodeId, property, value) {
    const nodeData = state.nodes.get(nodeId);
    nodeData[property] = value;
    
    const nodeEl = document.getElementById(`node-${nodeId}`);
    nodeEl.querySelector('.node-title').textContent = value;
    
    markNodeModified(nodeId);
    setModified(true);
}

export function updateNodeConfig(nodeId, key, value) {
    const nodeData = state.nodes.get(nodeId);
    nodeData.config[key] = value;
    
    // If outputs property changed, update the node's output ports
    if (key === 'outputs') {
        updateNodeOutputCount(nodeId, parseInt(value, 10));
    }
    
    // If input_count property changed, update the node's input ports
    if (key === 'input_count') {
        updateNodeInputCount(nodeId, parseInt(value, 10));
    }
    
    // Live-refresh an on-card config badge (e.g. a Link node's channel) so the
    // card reflects the edited value without a full re-render.
    const nodeEl = document.getElementById(`node-${nodeId}`);
    const badge = nodeEl && nodeEl.querySelector('.node-config-badge');
    if (badge && badge.dataset.key === key) {
        badge.textContent = value
            ? `${badge.dataset.prefix || ''}${value}`
            : (badge.dataset.placeholder || '');
    }

    // Live-refresh an on-card control slider when its range/value/label is
    // edited in the properties panel, so the card reflects it without a full
    // re-render (which would drop a slider mid-interaction).
    const slider = nodeEl && nodeEl.querySelector('.control-slider');
    if (slider) {
        if (key === 'value') {
            slider.value = value;
            const valEl = document.getElementById(`slider-val-${nodeId}`);
            if (valEl) valEl.textContent = value;
        } else if (key === 'min' || key === 'max' || key === 'step') {
            slider.setAttribute(key, value);
        } else if (key === 'label') {
            const labelEl = document.getElementById(`slider-label-${nodeId}`);
            if (labelEl) labelEl.textContent = value;
        }
    }

    // Let a mounted node editor re-sync anything it derives from this key.
    notifyEditorsOfConfigChange(nodeId, key, value);

    // Update property visibility since config changed
    window.updatePropertyVisibility(nodeId);

    markNodeModified(nodeId);
    setModified(true);
}

export function updateMultiselectConfig(nodeId, propName, checkbox) {
    const nodeData = state.nodes.get(nodeId);
    if (!nodeData) return;
    
    // Get the parent multiselect container
    const container = checkbox.closest('.property-multiselect');
    if (!container) return;
    
    // Collect all checked values
    const checkedValues = [];
    container.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
        checkedValues.push(cb.value);
    });
    
    nodeData.config[propName] = checkedValues;
    
    // Update property visibility since config changed
    window.updatePropertyVisibility(nodeId);
    
    markNodeModified(nodeId);
    setModified(true);
}

// Make it available globally
window.updateMultiselectConfig = updateMultiselectConfig;

export async function triggerNodeAction(nodeId, action) {
    try {
        await fetch(`${API_BASE}/nodes/${nodeId}/${action}`, { method: 'POST' });
    } catch (error) {
        console.error(`Failed to trigger ${action} on node:`, error);
    }
}

/**
 * Trigger a toggle action and sync state between properties panel and node UI.
 * @param {string} nodeId - The node ID
 * @param {string} action - The action to call (e.g., 'toggle_drawing')
 * @param {string} stateField - The field in nodeData to update (e.g., 'drawingEnabled')
 * @param {boolean} checked - The new toggle state
 */
export async function triggerToggleAction(nodeId, action, stateField, checked) {
    try {
        // Call the action endpoint
        const response = await fetch(`${API_BASE}/nodes/${nodeId}/${action}`, { method: 'POST' });
        
        if (response.ok) {
            // Update nodeData state
            const nodeData = state.nodes.get(nodeId);
            if (nodeData) {
                nodeData[stateField] = checked;
            }
            
            // Sync the toggle on the node itself (if it has one)
            const nodeToggle = document.getElementById(`toggle-${nodeId}`);
            if (nodeToggle && nodeToggle.checked !== checked) {
                nodeToggle.checked = checked;
            }
        }
    } catch (error) {
        console.error(`Failed to trigger ${action} on node:`, error);
    }
}

/**
 * Generic function to toggle node enabled state.
 * Consolidates toggleGate, toggleDebug, and toggleNodeEnabled into one function.
 * @param {string} nodeId - The node ID
 * @param {boolean} enabled - The new enabled state
 * @param {Object} options - Optional configuration
 * @param {string} options.checkboxSelector - CSS selector for checkbox to sync (e.g., '#gate-{nodeId}')
 */
export async function toggleNodeState(nodeId, enabled, options = {}) {
    try {
        const response = await fetch(`${API_BASE}/nodes/${nodeId}/enabled`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        
        const nodeData = state.nodes.get(nodeId);
        if (nodeData) {
            nodeData.enabled = enabled;
            
            // Update node visual state
            const nodeEl = document.getElementById(`node-${nodeId}`);
            if (nodeEl) {
                nodeEl.classList.toggle('disabled', !enabled);
            }
            
            // Update connections (dashed when disabled)
            updateConnections();
            
            // Update any visual toggle switches on the node (DebugNode, GateNode)
            const gateCheckbox = document.getElementById(`gate-${nodeId}`);
            const debugCheckbox = document.getElementById(`debug-${nodeId}`);
            if (gateCheckbox) gateCheckbox.checked = enabled;
            if (debugCheckbox) debugCheckbox.checked = enabled;
            
            // Sync properties panel if this node is selected
            if (state.selectedNode === nodeId) {
                const propsToggle = document.querySelector('#properties-panel .gate-switch input');
                if (propsToggle) propsToggle.checked = enabled;
            }
        }
    } catch (error) {
        console.error('Failed to toggle node state:', error);
    }
}

// Backwards compatibility aliases
export const toggleGate = toggleNodeState;
export const toggleNodeEnabled = toggleNodeState;

/**
 * Opens a file dialog to select a file and updates the node config.
 * Uses XMLHttpRequest for upload progress tracking.
 * @param {string} nodeId - The node ID
 * @param {string} propName - The property name to update
 * @param {string} accept - Comma-separated list of accepted file extensions
 * @param {string} uploadRoute - Optional node-specific upload route (e.g. 'upload_video')
 */
export function selectFile(nodeId, propName, accept, uploadRoute) {
    const input = document.createElement('input');
    input.type = 'file';
    if (accept) {
        input.accept = accept;
    }
    
    input.onchange = (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        const formData = new FormData();
        formData.append('file', file);
        
        let url;
        if (uploadRoute) {
            url = `${API_BASE}/nodes/${nodeId}/${uploadRoute}`;
        } else {
            formData.append('nodeId', nodeId);
            url = `${API_BASE}/upload/file`;
        }
        
        // Progress bar elements
        const fileId = `file-${nodeId}-${propName}`;
        const progressContainer = document.getElementById(`${fileId}-progress`);
        const progressFill = document.getElementById(`${fileId}-fill`);
        const progressText = document.getElementById(`${fileId}-text`);
        
        const xhr = new XMLHttpRequest();
        
        xhr.upload.addEventListener('progress', (evt) => {
            if (evt.lengthComputable && progressContainer) {
                const pct = Math.round((evt.loaded / evt.total) * 100);
                progressContainer.style.display = '';
                progressFill.style.width = `${pct}%`;
                progressText.textContent = `${pct}%`;
            }
        });
        
        xhr.addEventListener('load', () => {
            // Hide progress bar
            if (progressContainer) progressContainer.style.display = 'none';
            
            if (xhr.status >= 200 && xhr.status < 300) {
                try {
                    const result = JSON.parse(xhr.responseText);
                    if (result.success) {
                        const filePath = result.file_path || result.model_path;
                        updateNodeConfig(nodeId, propName, filePath);
                        
                        const nodeData = state.nodes.get(nodeId);
                        renderProperties(nodeData);
                        
                        showToast(`Uploaded: ${file.name}`);
                    } else {
                        showToast(`Upload failed: ${result.error}`, 'error');
                    }
                } catch (parseErr) {
                    showToast(`Upload failed: invalid server response`, 'error');
                }
            } else {
                let errorMsg = `Upload failed (${xhr.status})`;
                try {
                    const errResult = JSON.parse(xhr.responseText);
                    errorMsg = errResult.error || errResult.message || errorMsg;
                } catch (_) { /* use default */ }
                showToast(errorMsg, 'error');
            }
        });
        
        xhr.addEventListener('error', () => {
            if (progressContainer) progressContainer.style.display = 'none';
            showToast('Upload failed: network error', 'error');
        });
        
        xhr.addEventListener('abort', () => {
            if (progressContainer) progressContainer.style.display = 'none';
        });
        
        xhr.open('POST', url);
        xhr.send(formData);
    };
    
    input.click();
}

// Rules editor for switch node
window.updatePropertyVisibility = function(nodeId) {
    const nodeData = state.nodes.get(nodeId);
    if (!nodeData) return;
    
    const nodeType = getNodeType(nodeData.type);
    if (!nodeType || !nodeType.properties) return;
    
    // Get all property groups
    const propertyGroups = document.querySelectorAll('.property-group[data-show-if]');
    
    propertyGroups.forEach(group => {
        const showIfStr = group.getAttribute('data-show-if');
        if (!showIfStr) return;
        
        try {
            const showIf = JSON.parse(showIfStr);
            const shouldShow = shouldShowProperty(showIf, nodeData.config);
            
            if (shouldShow) {
                group.style.display = '';
            } else {
                group.style.display = 'none';
            }
        } catch (e) {
            console.error('Error parsing showIf condition:', e);
        }
    });
};
