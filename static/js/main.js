// Main application entry point
import { loadNodeTypes } from './palette.js';
import { setupEventListeners } from './events.js';
import { loadWorkflow } from './workflow.js';
import { startDebugPolling } from './debug.js';
import { updateNodeProperty, updateNodeConfig, triggerNodeAction, toggleNodeState, toggleGate, toggleNodeEnabled, addRule, removeRule, updateRule, addInjectProp, removeInjectProp, updateInjectProp } from './properties.js';

// Expose functions to window for inline event handlers
window.updateNodeProperty = updateNodeProperty;
window.updateNodeConfig = updateNodeConfig;
window.triggerNodeAction = triggerNodeAction;
window.toggleNodeState = toggleNodeState;
window.toggleGate = toggleGate;
window.toggleNodeEnabled = toggleNodeEnabled;
window.addRule = addRule;
window.removeRule = removeRule;
window.updateRule = updateRule;
window.addInjectProp = addInjectProp;
window.removeInjectProp = removeInjectProp;
window.updateInjectProp = updateInjectProp;

// Initialize application
document.addEventListener('DOMContentLoaded', async () => {
    await loadNodeTypes();
    setupEventListeners();
    await loadWorkflow();
    startDebugPolling();
});
