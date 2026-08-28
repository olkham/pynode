// Load the editor UI a node type ships with itself.
//
// /api/node-types carries a `uiAssets` field per node type (built from the
// node class's `ui_assets`); this pulls those in before the first properties
// panel can be rendered and hands each module to the registry.

import { listRegistered, registerModule } from './registry.js';

function collect(nodeTypes) {
    const js = new Set();
    const css = new Set();
    for (const nodeType of nodeTypes) {
        const assets = (nodeType && nodeType.uiAssets) || {};
        (assets.js || []).forEach(url => js.add(url));
        (assets.css || []).forEach(url => css.add(url));
    }
    return { js: [...js], css: [...css] };
}

function injectStylesheet(url) {
    if (document.querySelector(`link[data-node-ui="${CSS.escape(url)}"]`)) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = url;
    link.dataset.nodeUi = url;
    document.head.appendChild(link);
}

/**
 * Import every node-supplied UI module and register what it exports.
 *
 * Uses allSettled, not all: one node shipping a broken module must not blank
 * the editor. A module that fails to load simply leaves its property type
 * unregistered, and the panel then shows the "no editor registered" row for it
 * rather than rendering nothing at all.
 */
export async function loadNodeUiAssets(nodeTypes) {
    const { js, css } = collect(nodeTypes || []);

    css.forEach(injectStylesheet);

    const results = await Promise.allSettled(js.map(url => import(url)));
    results.forEach((result, i) => {
        if (result.status === 'fulfilled') {
            registerModule(result.value, js[i]);
        } else {
            console.error(`[node-ui] failed to load ${js[i]}:`, result.reason);
        }
    });

    // Answers "which file owns this editor?" from the console.
    window.nodeUiRegistry = listRegistered;
}
