// Node palette rendering
import { API_BASE, NODE_CATEGORIES } from './config.js';
import { state } from './state.js';

export async function loadNodeTypes() {
    try {
        const response = await fetch(`${API_BASE}/node-types`);
        state.nodeTypes = await response.json();
        renderNodePalette();
    } catch (error) {
        console.error('Failed to load node types:', error);
    }
}

export function renderNodePalette() {
    const palette = document.getElementById('node-palette');
    palette.innerHTML = '';

    // Dynamically group nodes by category, preserving order of first appearance
    const categories = {};
    state.nodeTypes.forEach(nodeType => {
        const category = nodeType.category || 'custom';
        if (!categories[category]) {
            categories[category] = {
                title: category.charAt(0).toUpperCase() + category.slice(1),
                nodes: []
            };
        }
        categories[category].nodes.push(nodeType);
    });

    // Render each category in order of appearance
    Object.values(categories).forEach(category => {
        if (category.nodes.length === 0) return;

        const categoryEl = document.createElement('div');
        categoryEl.className = 'palette-category';

        const headerEl = document.createElement('div');
        headerEl.className = 'palette-category-header';
        headerEl.textContent = category.title;
        categoryEl.appendChild(headerEl);

        const listEl = document.createElement('div');
        listEl.className = 'palette-category-list';

        category.nodes.forEach(nodeType => {
            const nodeEl = document.createElement('div');
            nodeEl.className = 'palette-node';

            const icon = nodeType.icon || '◆';
            const inputCount = nodeType.inputCount !== undefined ? nodeType.inputCount : 1;
            const outputCount = nodeType.outputCount !== undefined ? nodeType.outputCount : 1;

            const portsHtml = `
                <div class="palette-node-ports">
                    ${inputCount > 0 ? '<div class="palette-port input"></div>' : ''}
                    ${outputCount > 0 ? '<div class="palette-port output"></div>' : ''}
                </div>
            `;

            nodeEl.innerHTML = `
                <span class="palette-node-icon">${icon}</span>
                <span class="palette-node-name">${nodeType.name}</span>
                ${portsHtml}
            `;
            nodeEl.draggable = true;

            // Apply node colors
            if (nodeType.color) nodeEl.style.backgroundColor = nodeType.color;
            if (nodeType.borderColor) nodeEl.style.borderColor = nodeType.borderColor;
            if (nodeType.textColor) nodeEl.style.color = nodeType.textColor;

            nodeEl.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('nodeType', nodeType.type);

                // Store the offset from the top-left corner of the element
                const rect = nodeEl.getBoundingClientRect();
                const offsetX = e.clientX - rect.left;
                const offsetY = e.clientY - rect.top;
                e.dataTransfer.setData('dragOffsetX', offsetX.toString());
                e.dataTransfer.setData('dragOffsetY', offsetY.toString());
            });

            listEl.appendChild(nodeEl);
        });

        categoryEl.appendChild(listEl);
        palette.appendChild(categoryEl);
    });
}
