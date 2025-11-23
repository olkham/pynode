// Main application entry point
import { loadNodeTypes } from './palette.js';
import { setupEventListeners } from './events.js';
import { loadWorkflow } from './workflow.js';
import { startDebugPolling } from './debug.js';
import { updateNodeProperty, updateNodeConfig, triggerNodeAction, toggleGate } from './properties.js';

// Expose functions to window for inline event handlers
window.updateNodeProperty = updateNodeProperty;
window.updateNodeConfig = updateNodeConfig;
window.triggerNodeAction = triggerNodeAction;
window.toggleGate = toggleGate;

// Initialize application
document.addEventListener('DOMContentLoaded', async () => {
    await loadNodeTypes();
    setupEventListeners();
    await loadWorkflow();
    startDebugPolling();
});
