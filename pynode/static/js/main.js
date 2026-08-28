// Main application entry point
import { API_BASE } from './config.js';
import { loadNodeTypes } from './palette.js';
import { setupEventListeners } from './events.js';
import { loadWorkflow } from './workflow.js';
import { startDebugPolling } from './debug.js';
import { initViewport } from './viewport.js';
import { initMinimap } from './minimap.js';
import { updateNodeProperty, updateNodeConfig, triggerNodeAction, triggerToggleAction, toggleNodeState, toggleGate, toggleNodeEnabled, selectFile } from './properties.js';
import { showInfoPanel } from './ui-utils.js';

// Expose functions to window for the inline event handlers in the panel's
// remaining string-built rows. Node-supplied editors attach real listeners and
// need nothing here, which is why this list no longer grows with every node.
window.updateNodeProperty = updateNodeProperty;
window.updateNodeConfig = updateNodeConfig;
window.triggerNodeAction = triggerNodeAction;
window.triggerToggleAction = triggerToggleAction;
window.toggleNodeState = toggleNodeState;
window.toggleGate = toggleGate;
window.toggleNodeEnabled = toggleNodeEnabled;
window.selectFile = selectFile;
window.showInfoPanel = showInfoPanel;

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
