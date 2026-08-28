// Registry of node-supplied editor UI.
//
// A node type ships its own property editor as a JS module in its folder
// (declared via the node class's `ui_assets`). loader.js imports those modules
// at startup and hands each one here; properties.js then looks up an editor by
// `prop.type` instead of carrying a branch for it.
//
// Modules never import this file - the loader registers what they export - so
// a node's UI module has exactly one dependency on the core editor: the DOM
// helpers in ./dom.js.

const propertyEditors = new Map();   // prop.type -> {editor, source}

/**
 * Register a property editor for one `prop.type`.
 * @param {string} type - the property type, matching the node's Python schema
 * @param {object} editor - {mount(ctx) -> Element, ready?, destroy?, onConfigChange?}
 * @param {string} source - URL the editor came from, for diagnostics
 */
export function registerPropertyEditor(type, editor, source = '(unknown)') {
    if (typeof type !== 'string' || !type) {
        console.error(`[node-ui] ${source}: property editor has no 'propertyType'; ignoring.`);
        return;
    }
    if (!editor || typeof editor.mount !== 'function') {
        console.error(`[node-ui] ${source}: property editor '${type}' has no mount(); ignoring.`);
        return;
    }
    const existing = propertyEditors.get(type);
    if (existing) {
        // Two modules claiming one type is a real conflict, not a warning to
        // scroll past - say who is fighting over what.
        console.error(
            `[node-ui] property type '${type}' is already registered by ${existing.source}; ` +
            `${source} is overwriting it.`);
    }
    propertyEditors.set(type, { editor, source });
}

/** The editor registered for a property type, or undefined. */
export function getPropertyEditor(type) {
    const entry = propertyEditors.get(type);
    return entry ? entry.editor : undefined;
}

/**
 * Register everything a loaded node UI module exports.
 *
 * A module's default export is one entry, or an array of them. An entry
 * declares what it is via `propertyType`.
 */
export function registerModule(module, source) {
    const exported = module && module.default;
    if (!exported) {
        console.error(`[node-ui] ${source}: no default export; nothing registered.`);
        return;
    }
    for (const entry of (Array.isArray(exported) ? exported : [exported])) {
        if (entry && entry.propertyType) {
            registerPropertyEditor(entry.propertyType, entry, source);
        } else {
            console.error(`[node-ui] ${source}: export declares no 'propertyType'; ignoring.`);
        }
    }
}

/**
 * What is registered, and where each came from. Exposed on
 * `window.nodeUiRegistry` by loader.js so "which file owns this editor?" is
 * answerable from the console now that the answer is no longer one grep.
 */
export function listRegistered() {
    return [...propertyEditors.entries()]
        .map(([type, { source }]) => ({ propertyType: type, source }))
        .sort((a, b) => a.propertyType.localeCompare(b.propertyType));
}
