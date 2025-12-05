// Properties panel
import { state, markNodeModified, setModified, getNodeType } from './state.js';
import { API_BASE } from './config.js';
import { updateNodeOutputCount, updateNodeInputCount } from './nodes.js';
import { updateConnections } from './connections.js';

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
    
    let html = `
        <div class="property-group">
            <label class="property-label">Name</label>
            <input type="text" class="property-input" value="${nodeData.name}" 
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
                           value="${value}"
                           placeholder="${placeholder}"
                           onchange="window.updateNodeConfig('${nodeData.id}', '${prop.name}', this.value)">
                `;
            } else if (prop.type === 'number') {
                const value = nodeData.config[prop.name] !== undefined ? nodeData.config[prop.name] : (prop.default || 0);
                html += `
                    <label class="property-label">${prop.label}</label>
                    <input type="number" class="property-input" 
                           value="${value}"
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
                              placeholder="${placeholder}"
                              onchange="window.updateNodeConfig('${nodeData.id}', '${prop.name}', this.value)">${value}</textarea>
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
                html += '</select>';
            } else if (prop.type === 'button') {
                html += `
                    <button class="btn btn-primary" onclick="window.triggerNodeAction('${nodeData.id}', '${prop.action}')">${prop.label}</button>
                `;
            } else if (prop.type === 'rules') {
                html += renderRulesEditor(nodeData.id, prop.name, nodeData.config[prop.name] || []);
            } else if (prop.type === 'injectProps') {
                html += renderInjectPropsEditor(nodeData.id, prop.name, nodeData.config[prop.name] || []);
            }
            
            if (prop.help) {
                html += `<small class="property-help">${prop.help}</small>`;
            }
            
            html += '</div>';
        });
    }
    
    panel.innerHTML = html;
    
    // Update property visibility based on current config
    window.updatePropertyVisibility(nodeData.id);
}

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
    
    // Update property visibility since config changed
    window.updatePropertyVisibility(nodeId);
    
    markNodeModified(nodeId);
    setModified(true);
}

export async function triggerNodeAction(nodeId, action) {
    try {
        await fetch(`${API_BASE}/nodes/${nodeId}/${action}`, { method: 'POST' });
    } catch (error) {
        console.error(`Failed to trigger ${action} on node:`, error);
    }
}

export async function toggleGate(nodeId, open) {
    try {
        await fetch(`${API_BASE}/nodes/${nodeId}/enabled`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: open })
        });
        
        const nodeData = state.nodes.get(nodeId);
        if (nodeData) {
            nodeData.enabled = open;
            
            // Update node visual state
            const nodeEl = document.getElementById(`node-${nodeId}`);
            if (nodeEl) {
                nodeEl.classList.toggle('disabled', !open);
            }
            
            // Update connections (dashed when disabled)
            updateConnections();
            
            // Sync properties panel if this node is selected
            if (state.selectedNode === nodeId) {
                const propsToggle = document.querySelector('#properties-panel .gate-switch input');
                if (propsToggle) propsToggle.checked = open;
            }
        }
    } catch (error) {
        console.error('Failed to toggle gate:', error);
    }
}

export async function toggleNodeEnabled(nodeId, enabled) {
    try {
        await fetch(`${API_BASE}/nodes/${nodeId}/enabled`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled })
        });
        
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
        }
    } catch (error) {
        console.error('Failed to toggle node enabled:', error);
    }
}

// Rules editor for switch node
function renderRulesEditor(nodeId, propName, rules) {
    let html = '<div class="rules-editor">';
    
    rules.forEach((rule, index) => {
        html += `
            <div class="rule-item" data-rule-index="${index}">
                <div class="rule-header">
                    <span class="rule-label">Rule ${index + 1} → Output ${index + 1}</span>
                    <button class="btn-icon" onclick="window.removeRule('${nodeId}', '${propName}', ${index})" title="Delete rule">✕</button>
                </div>
                <div class="rule-config">
                    <select class="rule-operator" onchange="window.updateRule('${nodeId}', '${propName}', ${index}, 'operator', this.value)">
                        ${getOperatorOptions(rule.operator || 'eq')}
                    </select>
                    <input type="text" class="rule-value" placeholder="Value" 
                           value="${rule.value || ''}"
                           onchange="window.updateRule('${nodeId}', '${propName}', ${index}, 'value', this.value)">
                    <select class="rule-type" onchange="window.updateRule('${nodeId}', '${propName}', ${index}, 'valueType', this.value)">
                        ${getValueTypeOptions(rule.valueType || 'str')}
                    </select>
                </div>
            </div>
        `;
    });
    
    html += `
        <button class="btn btn-secondary" onclick="window.addRule('${nodeId}', '${propName}')">+ Add Rule</button>
    </div>`;
    
    return html;
}

function getOperatorOptions(selected) {
    const operators = [
        { value: 'eq', label: '==' },
        { value: 'neq', label: '!=' },
        { value: 'lt', label: '<' },
        { value: 'lte', label: '<=' },
        { value: 'gt', label: '>' },
        { value: 'gte', label: '>=' },
        { value: 'between', label: 'between' },
        { value: 'contains', label: 'contains' },
        { value: 'matches', label: 'matches regex' },
        { value: 'true', label: 'is true' },
        { value: 'false', label: 'is false' },
        { value: 'null', label: 'is null' },
        { value: 'nnull', label: 'is not null' },
        { value: 'empty', label: 'is empty' },
        { value: 'nempty', label: 'is not empty' },
        { value: 'haskey', label: 'has key' },
        { value: 'else', label: 'otherwise' }
    ];
    
    return operators.map(op => 
        `<option value="${op.value}" ${op.value === selected ? 'selected' : ''}>${op.label}</option>`
    ).join('');
}

function getValueTypeOptions(selected) {
    const types = [
        { value: 'str', label: 'string' },
        { value: 'num', label: 'number' },
        { value: 'bool', label: 'boolean' },
        { value: 'json', label: 'JSON' }
    ];
    
    return types.map(type => 
        `<option value="${type.value}" ${type.value === selected ? 'selected' : ''}>${type.label}</option>`
    ).join('');
}

export function addRule(nodeId, propName) {
    const nodeData = state.nodes.get(nodeId);
    const rules = nodeData.config[propName] || [];
    
    rules.push({
        operator: 'eq',
        value: '',
        valueType: 'str'
    });
    
    nodeData.config[propName] = rules;
    
    // Update output count to match rules
    updateNodeOutputCount(nodeId, rules.length);
    
    markNodeModified(nodeId);
    setModified(true);
    renderProperties(nodeData);
}

export function removeRule(nodeId, propName, ruleIndex) {
    const nodeData = state.nodes.get(nodeId);
    const rules = nodeData.config[propName] || [];
    
    if (rules.length > 1) {
        rules.splice(ruleIndex, 1);
        nodeData.config[propName] = rules;
        
        // Update output count to match rules
        updateNodeOutputCount(nodeId, rules.length);
        
        markNodeModified(nodeId);
        setModified(true);
        renderProperties(nodeData);
    }
}

export function updateRule(nodeId, propName, ruleIndex, field, value) {
    const nodeData = state.nodes.get(nodeId);
    const rules = nodeData.config[propName] || [];
    
    if (rules[ruleIndex]) {
        rules[ruleIndex][field] = value;
        nodeData.config[propName] = rules;
        
        markNodeModified(nodeId);
        setModified(true);
    }
}

// Inject properties editor for inject node
function renderInjectPropsEditor(nodeId, propName, props) {
    let html = '<div class="inject-props-editor">';
    
    props.forEach((prop, index) => {
        html += `
            <div class="inject-prop-row" data-prop-index="${index}">
                <span class="inject-prop-prefix">msg.</span>
                <input type="text" class="inject-prop-key" placeholder="payload" 
                       value="${prop.property || ''}"
                       onchange="window.updateInjectProp('${nodeId}', '${propName}', ${index}, 'property', this.value)">
                <span class="inject-prop-eq">=</span>
                <select class="inject-prop-type" onchange="window.updateInjectProp('${nodeId}', '${propName}', ${index}, 'valueType', this.value)">
                    ${getInjectValueTypeOptions(prop.valueType || 'str')}
                </select>
                ${renderInjectValueInput(nodeId, propName, index, prop)}
                <button class="btn-icon-sm" onclick="window.removeInjectProp('${nodeId}', '${propName}', ${index})" title="Delete">✕</button>
            </div>
        `;
    });
    
    html += `
        <button class="btn btn-secondary btn-sm" onclick="window.addInjectProp('${nodeId}', '${propName}')">+ Add</button>
    </div>`;
    
    return html;
}

function getInjectValueTypeOptions(selected) {
    const types = [
        { value: 'str', icon: 'az', label: 'string' },
        { value: 'num', icon: '123', label: 'number' },
        { value: 'bool', icon: 't/f', label: 'boolean' },
        { value: 'json', icon: '{ }', label: 'JSON' },
        { value: 'date', icon: '⏱', label: 'timestamp' },
        { value: 'env', icon: 'env', label: 'env variable' }
    ];
    
    return types.map(type => 
        `<option value="${type.value}" ${type.value === selected ? 'selected' : ''} data-icon="${type.icon}">${type.value === selected ? type.icon : type.label}</option>`
    ).join('');
}

function renderInjectValueInput(nodeId, propName, index, prop) {
    const valueType = prop.valueType || 'str';
    const value = prop.value !== undefined ? prop.value : '';
    
    if (valueType === 'date') {
        return '<input type="text" class="inject-prop-value" disabled placeholder="timestamp">';
    } else if (valueType === 'bool') {
        return `<select class="inject-prop-value" onchange="window.updateInjectProp('${nodeId}', '${propName}', ${index}, 'value', this.value)"><option value="true" ${value === 'true' || value === true ? 'selected' : ''}>true</option><option value="false" ${value === 'false' || value === false ? 'selected' : ''}>false</option></select>`;
    } else if (valueType === 'json') {
        const escaped = String(value).replace(/"/g, '&quot;');
        return `<input type="text" class="inject-prop-value inject-prop-json" placeholder='{"key":"value"}' value="${escaped}" onchange="window.updateInjectProp('${nodeId}', '${propName}', ${index}, 'value', this.value)">`;
    } else {
        const placeholder = valueType === 'num' ? '0' : valueType === 'env' ? 'ENV_VAR' : '';
        return `<input type="text" class="inject-prop-value" placeholder="${placeholder}" value="${value}" onchange="window.updateInjectProp('${nodeId}', '${propName}', ${index}, 'value', this.value)">`;
    }
}

export function addInjectProp(nodeId, propName) {
    const nodeData = state.nodes.get(nodeId);
    const props = nodeData.config[propName] || [];
    
    props.push({
        property: 'payload',
        valueType: 'date',
        value: ''
    });
    
    nodeData.config[propName] = props;
    
    markNodeModified(nodeId);
    setModified(true);
    renderProperties(nodeData);
}

export function removeInjectProp(nodeId, propName, propIndex) {
    const nodeData = state.nodes.get(nodeId);
    const props = nodeData.config[propName] || [];
    
    if (props.length > 0) {
        props.splice(propIndex, 1);
        nodeData.config[propName] = props;
        
        markNodeModified(nodeId);
        setModified(true);
        renderProperties(nodeData);
    }
}

export function updateInjectProp(nodeId, propName, propIndex, field, value) {
    const nodeData = state.nodes.get(nodeId);
    const props = nodeData.config[propName] || [];
    
    if (props[propIndex]) {
        props[propIndex][field] = value;
        nodeData.config[propName] = props;
        
        // Re-render if type changed to update value input
        if (field === 'valueType') {
            renderProperties(nodeData);
        }
        
        markNodeModified(nodeId);
        setModified(true);
    }
}

// Update property visibility based on current config values
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
