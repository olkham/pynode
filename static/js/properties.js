// Properties panel
import { state, markNodeModified, setModified } from './state.js';
import { API_BASE } from './config.js';

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
        await fetch(`${API_BASE}/nodes/${nodeId}/gate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ open })
        });
        
        const nodeData = state.nodes.get(nodeId);
        if (nodeData) {
            nodeData.gateOpen = open;
        }
    } catch (error) {
        console.error('Failed to toggle gate:', error);
    }
}
