// Main application entry point
import { loadNodeTypes } from './palette.js';
import { setupEventListeners } from './events.js';
import { loadWorkflow } from './workflow.js';
import { startDebugPolling } from './debug.js';
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

// Initialize application
document.addEventListener('DOMContentLoaded', async () => {
    await loadNodeTypes();
    setupEventListeners();
    await loadWorkflow();
    startDebugPolling();
});
