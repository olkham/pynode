// Node palette rendering
import { API_BASE, NODE_CATEGORIES } from './config.js';
import { state, setNodeTypes } from './state.js';
import { categoryLabel } from './ui-utils.js';

// Collapsed-state of categories, keyed by lowercase category value and
// persisted in localStorage. On very first load (no stored state) large
// categories (> LARGE_CATEGORY_THRESHOLD nodes, e.g. OpenCV) start collapsed.
const COLLAPSED_STORAGE_KEY = 'pynode.palette.collapsedCategories';
const LARGE_CATEGORY_THRESHOLD = 10;
let collapsedCategories = null; // Set of lowercase category keys (lazy init)

function initCollapsedCategories(categories) {
    if (collapsedCategories) return;

    const stored = localStorage.getItem(COLLAPSED_STORAGE_KEY);
    if (stored !== null) {
        try {
            collapsedCategories = new Set(JSON.parse(stored));
            return;
        } catch (e) {
            console.warn('Ignoring corrupt palette collapse state:', e);
        }
    }

    // First load: collapse large categories by default
    collapsedCategories = new Set();
    Object.entries(categories).forEach(([key, category]) => {
        if (category.nodes.length > LARGE_CATEGORY_THRESHOLD) {
            collapsedCategories.add(key);
        }
    });
    saveCollapsedCategories();
}

function saveCollapsedCategories() {
    localStorage.setItem(COLLAPSED_STORAGE_KEY, JSON.stringify([...collapsedCategories]));
}

export async function loadNodeTypes() {
    try {
        const response = await fetch(`${API_BASE}/node-types`);
        const types = await response.json();
        setNodeTypes(types);  // Use the setter to build both array and map
        renderNodePalette();
        setupPaletteSearch();
    } catch (error) {
        console.error('Failed to load node types:', error);
    }
}

function setupPaletteSearch() {
    const searchInput = document.getElementById('palette-search');
    const clearBtn = document.getElementById('palette-clear-btn');
    if (!searchInput) return;
    
    const updateClearVisibility = () => {
        if (!clearBtn) return;
        clearBtn.style.display = searchInput.value.trim() ? 'block' : 'none';
    };

    searchInput.addEventListener('input', (e) => {
        const filter = e.target.value.toLowerCase().trim();
        filterPaletteNodes(filter);
        updateClearVisibility();
    });

    if (clearBtn) {
        clearBtn.addEventListener('click', (e) => {
            e.preventDefault();
            searchInput.value = '';
            filterPaletteNodes('');
            updateClearVisibility();
            searchInput.focus();
        });
        // Initialize visibility
        updateClearVisibility();
    }
}

function filterPaletteNodes(filter) {
    const palette = document.getElementById('node-palette');
    const categories = palette.querySelectorAll('.palette-category');
    
    categories.forEach(category => {
        const nodes = category.querySelectorAll('.palette-node');
        let visibleCount = 0;
        
        nodes.forEach(node => {
            const nodeName = node.querySelector('.palette-node-name').textContent.toLowerCase();
            if (!filter || nodeName.includes(filter)) {
                node.style.display = '';
                visibleCount++;
            } else {
                node.style.display = 'none';
            }
        });
        
        // Hide category if no nodes match
        category.style.display = visibleCount > 0 ? '' : 'none';
    });
}

export function renderNodePalette() {
    const palette = document.getElementById('node-palette');
    palette.innerHTML = '';

    // Dynamically group nodes by category (case-insensitively, so 'opencv'
    // and 'OpenCV' land in the same bucket), preserving the server-provided
    // order of first appearance.
    const categories = {};
    state.nodeTypes.forEach(nodeType => {
        const key = String(nodeType.category || 'custom').toLowerCase();
        if (!categories[key]) {
            categories[key] = {
                key: key,
                title: categoryLabel(key),
                nodes: []
            };
        }
        categories[key].nodes.push(nodeType);
    });

    initCollapsedCategories(categories);

    // Render each category in order of appearance
    Object.values(categories).forEach(category => {
        if (category.nodes.length === 0) return;

        const categoryEl = document.createElement('div');
        categoryEl.className = 'palette-category';

        const headerEl = document.createElement('div');
        headerEl.className = 'palette-category-header';

        // Add collapse arrow
        const arrowEl = document.createElement('span');
        arrowEl.className = 'palette-category-arrow';
        arrowEl.textContent = '▼';
        if (collapsedCategories.has(category.key)) {
            arrowEl.classList.add('collapsed');
        }
        headerEl.appendChild(arrowEl);

        const titleEl = document.createElement('span');
        titleEl.textContent = category.title;
        headerEl.appendChild(titleEl);

        // Add node count badge
        const countEl = document.createElement('span');
        countEl.className = 'palette-category-count';
        countEl.textContent = category.nodes.length;
        headerEl.appendChild(countEl);

        categoryEl.appendChild(headerEl);

        const listEl = document.createElement('div');
        listEl.className = 'palette-category-list';

        // Apply collapsed state
        if (collapsedCategories.has(category.key)) {
            listEl.classList.add('collapsed');
            arrowEl.classList.add('collapsed');
        }

        // Toggle collapse on header click
        headerEl.addEventListener('click', () => {
            const isCollapsed = listEl.classList.contains('collapsed');

            if (isCollapsed) {
                // Expand: set max-height to scrollHeight for animation
                listEl.style.maxHeight = listEl.scrollHeight + 'px';
                listEl.classList.remove('collapsed');
                arrowEl.classList.remove('collapsed');
                collapsedCategories.delete(category.key);

                // After animation, remove max-height to allow dynamic content
                setTimeout(() => {
                    if (!listEl.classList.contains('collapsed')) {
                        listEl.style.maxHeight = 'none';
                    }
                }, 250);
            } else {
                // Collapse: first set explicit max-height, then collapse
                listEl.style.maxHeight = listEl.scrollHeight + 'px';
                // Force reflow
                listEl.offsetHeight;
                listEl.classList.add('collapsed');
                arrowEl.classList.add('collapsed');
                collapsedCategories.add(category.key);
            }
            saveCollapsedCategories();
        });

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

                // Center the node on the pointer
                const rect = nodeEl.getBoundingClientRect();
                const offsetX = rect.width / 2;
                const offsetY = rect.height / 2;
                e.dataTransfer.setData('dragOffsetX', offsetX.toString());
                e.dataTransfer.setData('dragOffsetY', offsetY.toString());
                
                // Create a custom drag image that isn't faded
                const dragImage = nodeEl.cloneNode(true);
                dragImage.style.position = 'absolute';
                dragImage.style.top = '-1000px';
                dragImage.style.left = '-1000px';
                dragImage.style.opacity = '1';
                dragImage.style.transform = 'none';
                dragImage.style.pointerEvents = 'none';
                document.body.appendChild(dragImage);
                e.dataTransfer.setDragImage(dragImage, offsetX, offsetY);
                
                // Clean up the drag image after a short delay
                setTimeout(() => {
                    document.body.removeChild(dragImage);
                }, 0);
            });

            listEl.appendChild(nodeEl);
        });

        categoryEl.appendChild(listEl);
        palette.appendChild(categoryEl);
    });
}
