// Properties panel
import { state, markNodeModified, setModified } from './state.js';
import { API_BASE } from './config.js';
import { updateNodeOutputCount } from './nodes.js';

export function renderProperties(nodeData) {
    const panel = document.getElementById('properties-panel');
    
    let html = `
        <div class="property-group">
            <label class="property-label">Name</label>
            <input type="text" class="property-input" value="${nodeData.name}" 
                   onchange="window.updateNodeProperty('${nodeData.id}', 'name', this.value)">
        </div>
    `;
    
    const nodeType = state.nodeTypes.find(nt => nt.type === nodeData.type);
    if (nodeType && nodeType.properties) {
        nodeType.properties.forEach(prop => {
            html += '<div class="property-group">';
            
            if (prop.type === 'text') {
                html += `
                    <label class="property-label">${prop.label}</label>
                    <input type="text" class="property-input" 
                           value="${nodeData.config[prop.name] || ''}"
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
                html += `
                    <label class="property-label">${prop.label}</label>
                    <textarea class="property-input property-textarea" 
                              onchange="window.updateNodeConfig('${nodeData.id}', '${prop.name}', this.value)">${nodeData.config[prop.name] || ''}</textarea>
                `;
            } else if (prop.type === 'select') {
                html += `
                    <label class="property-label">${prop.label}</label>
                    <select class="property-select" 
                            onchange="window.updateNodeConfig('${nodeData.id}', '${prop.name}', this.value)">
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
            }
            
            if (prop.help) {
                html += `<small class="property-help">${prop.help}</small>`;
            }
            
            html += '</div>';
        });
    }
    
    panel.innerHTML = html;
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
        }
    } catch (error) {
        console.error('Failed to toggle gate:', error);
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
