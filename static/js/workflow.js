// Workflow import/export and deployment
import { API_BASE } from './config.js';
import { state, setModified, clearAllNodeModifiedIndicators } from './state.js';
import { renderNode } from './nodes.js';
import { updateConnections } from './connections.js';
import { showToast } from './ui-utils.js';
import { deselectAllNodes } from './selection.js';

export async function loadWorkflow() {
    try {
        const response = await fetch(`${API_BASE}/workflow`);
        const workflow = await response.json();
        
        state.nodes.clear();
        state.connections = [];
        document.getElementById('nodes-container').innerHTML = '';
        document.getElementById('connections').innerHTML = '';
        
        // First, process all node data with async operations
        const nodePromises = workflow.nodes.map(async (nodeData) => {
            nodeData.x = nodeData.x !== undefined ? nodeData.x : 100;
            nodeData.y = nodeData.y !== undefined ? nodeData.y : 100;
            
            const nodeType = state.nodeTypes.find(nt => nt.type === nodeData.type);
            if (nodeType) {
                nodeData.color = nodeType.color;
                nodeData.borderColor = nodeType.borderColor;
                nodeData.textColor = nodeType.textColor;
                nodeData.icon = nodeType.icon;
                nodeData.inputCount = nodeType.inputCount;
                nodeData.outputCount = nodeType.outputCount;
                
                // Handle dynamic output counts (e.g., SwitchNode)
                if (nodeData.type === 'SwitchNode' && nodeData.config && nodeData.config.rules) {
                    nodeData.outputCount = Math.max(1, nodeData.config.rules.length);
                }
            }
            
            if (nodeData.type === 'GateNode') {
                try {
                    const enabledResponse = await fetch(`${API_BASE}/nodes/${nodeData.id}/enabled`);
                    const enabledData = await enabledResponse.json();
                    nodeData.enabled = enabledData.enabled;
                } catch (error) {
                    nodeData.enabled = true;
                }
            }
            
            if (nodeData.type === 'DebugNode') {
                try {
                    const enabledResponse = await fetch(`${API_BASE}/nodes/${nodeData.id}/enabled`);
                    const enabledData = await enabledResponse.json();
                    nodeData.enabled = enabledData.enabled;
                } catch (error) {
                    nodeData.enabled = true;
                }
            }
            
            return nodeData;
        });
        
        // Wait for all async operations to complete
        const processedNodes = await Promise.all(nodePromises);
        
        // Now render all nodes synchronously
        processedNodes.forEach(nodeData => {
            state.nodes.set(nodeData.id, nodeData);
            renderNode(nodeData);
        });
        
        // Load connections into state
        workflow.connections.forEach(conn => {
            state.connections.push(conn);
        });
        
        // Render connections immediately after nodes are in DOM
        updateConnections();
        
        // Clear history after loading workflow
        import('./history.js').then(({ clearHistory }) => {
            clearHistory();
        });
        
        setModified(false);
    } catch (error) {
        console.error('Failed to load workflow:', error);
    }
}

export async function deployWorkflow() {
    try {
        const nodes = [];
        state.nodes.forEach((nodeData) => {
            nodes.push({
                id: nodeData.id,
                type: nodeData.type,
                name: nodeData.name,
                config: nodeData.config,
                enabled: nodeData.enabled !== undefined ? nodeData.enabled : true,
                x: nodeData.x,
                y: nodeData.y
            });
        });
        
        const workflow = {
            nodes: nodes,
            connections: state.connections
        };
        
        const response = await fetch(`${API_BASE}/workflow`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(workflow)
        });
        
        if (response.ok) {
            clearAllNodeModifiedIndicators();
            setModified(false);
            showToast('Workflow deployed and saved!');
        } else {
            throw new Error('Failed to deploy workflow');
        }
    } catch (error) {
        console.error('Failed to deploy workflow:', error);
        showToast('Failed to deploy workflow');
    }
}

export function clearWorkflow() {
    if (!confirm('Clear all nodes and connections?')) return;
    
    state.nodes.clear();
    state.connections = [];
    
    document.getElementById('nodes-container').innerHTML = '';
    document.getElementById('connections').innerHTML = '';
    
    deselectAllNodes();
    
    // Clear history when clearing workflow
    import('./history.js').then(({ clearHistory }) => {
        clearHistory();
    });
    
    setModified(true);
}

export function exportWorkflow() {
    try {
        const nodes = [];
        state.nodes.forEach((nodeData) => {
            nodes.push({
                id: nodeData.id,
                type: nodeData.type,
                name: nodeData.name,
                config: nodeData.config,
                x: nodeData.x,
                y: nodeData.y
            });
        });
        
        const workflow = {
            nodes: nodes,
            connections: state.connections
        };
        
        const dataStr = JSON.stringify(workflow, null, 2);
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(dataBlob);
        
        const link = document.createElement('a');
        link.href = url;
        link.download = 'workflow.json';
        link.click();
    } catch (error) {
        console.error('Failed to export workflow:', error);
    }
}

export function importWorkflow() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/json';
    
    input.onchange = async (e) => {
        const file = e.target.files[0];
        const text = await file.text();
        const workflow = JSON.parse(text);
        
        try {
            state.nodes.clear();
            state.connections = [];
            document.getElementById('nodes-container').innerHTML = '';
            document.getElementById('connections').innerHTML = '';
            
            workflow.nodes.forEach(nodeData => {
                const nodeType = state.nodeTypes.find(nt => nt.type === nodeData.type);
                if (nodeType) {
                    nodeData.color = nodeType.color;
                    nodeData.borderColor = nodeType.borderColor;
                    nodeData.textColor = nodeType.textColor;
                    nodeData.icon = nodeType.icon;
                    nodeData.inputCount = nodeType.inputCount;
                    nodeData.outputCount = nodeType.outputCount;
                    
                    // Handle dynamic output counts (e.g., SwitchNode)
                    if (nodeData.type === 'SwitchNode' && nodeData.config && nodeData.config.rules) {
                        nodeData.outputCount = Math.max(1, nodeData.config.rules.length);
                    }
                }
                
                state.nodes.set(nodeData.id, nodeData);
                renderNode(nodeData);
            });
            
            workflow.connections.forEach(conn => {
                state.connections.push(conn);
                renderConnection(conn);
            });
            
            // Clear history after importing workflow
            import('./history.js').then(({ clearHistory }) => {
                clearHistory();
            });
            
            setModified(true);
            showToast('Workflow imported. Deploy to activate.');
        } catch (error) {
            console.error('Failed to import workflow:', error);
            showToast('Failed to import workflow');
        }
    };
    
    input.click();
}
