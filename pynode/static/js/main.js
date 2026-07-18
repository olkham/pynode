// Main application entry point
import { API_BASE } from './config.js';
import { loadNodeTypes } from './palette.js';
import { setupEventListeners } from './events.js';
import { loadWorkflow } from './workflow.js';
import { startDebugPolling } from './debug.js';
import { initViewport } from './viewport.js';
import { initMinimap } from './minimap.js';
import { updateNodeProperty, updateNodeConfig, triggerNodeAction, triggerToggleAction, toggleNodeState, toggleGate, toggleNodeEnabled, addRule, removeRule, updateRule, addInjectProp, removeInjectProp, updateInjectProp, addChangeRule, removeChangeRule, updateChangeRule, selectFile } from './properties.js';

// Expose functions to window for inline event handlers
window.updateNodeProperty = updateNodeProperty;
window.updateNodeConfig = updateNodeConfig;
window.triggerNodeAction = triggerNodeAction;
window.triggerToggleAction = triggerToggleAction;
window.toggleNodeState = toggleNodeState;
window.toggleGate = toggleGate;
window.toggleNodeEnabled = toggleNodeEnabled;
window.addRule = addRule;
window.removeRule = removeRule;
window.updateRule = updateRule;
window.addInjectProp = addInjectProp;
window.removeInjectProp = removeInjectProp;
window.updateInjectProp = updateInjectProp;
window.addChangeRule = addChangeRule;
window.removeChangeRule = removeChangeRule;
window.updateChangeRule = updateChangeRule;
window.selectFile = selectFile;

// Fetch the running version and show it next to the title. Best-effort:
// failures leave the label blank rather than blocking startup.
async function loadVersion() {
    try {
        const response = await fetch(`${API_BASE}/version`);
        if (!response.ok) return;
        const data = await response.json();
        const el = document.getElementById('app-version');
        if (el && data.version) {
            // Show only the release part ("0.2.2.dev0+g46a6184ff" -> "v0.2.2");
            // keep the full version available as a tooltip.
            const short = (String(data.version).match(/^\d+\.\d+(?:\.\d+)?/) || [data.version])[0];
            el.textContent = `v${short}`;
            el.title = `v${data.version}`;
        }
    } catch (error) {
        console.warn('Could not load version:', error);
    }
}

// Initialize application
document.addEventListener('DOMContentLoaded', async () => {
    await loadNodeTypes();
    setupEventListeners();
    initViewport();
    initMinimap();
    await loadWorkflow();
    startDebugPolling();
    loadVersion();
});
