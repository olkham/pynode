// The context object handed to a node's property editor.
//
// This is the entire surface an editor gets. Editors do not import state.js,
// properties.js or nodes.js - everything they are allowed to do goes through
// here, which is what keeps the dependency arrow pointing one way and makes
// import cycles impossible.
//
// Core deps are injected by properties.js rather than imported here, so this
// module does not import the module that imports it.

import { API_BASE } from '../config.js';
import { state } from '../state.js';
import { copyText, showToast } from '../ui-utils.js';

/**
 * @param {object} args
 * @param {object} args.nodeData - the node being edited
 * @param {object} args.prop - the property's schema entry (from Python)
 * @param {object} args.deps - {updateConfig, setOutputCount, rerender}
 */
export function createPropertyContext({ nodeData, prop, deps }) {
    return {
        nodeId: nodeData.id,
        node: nodeData,
        prop,

        /** Current value of this property, falling back to the schema default. */
        get value() {
            const current = nodeData.config[prop.name];
            return current !== undefined ? current : prop.default;
        },

        /** Read another config key on this node. */
        getConfig(key) {
            return nodeData.config[key];
        },

        /**
         * Every node in the current editor, read-only. For editors that need
         * to see their siblings - a Link channel picker suggesting channels
         * typed into other Link nodes that are not deployed yet.
         */
        allNodes() {
            return [...state.nodes.values()];
        },

        /** Write this property. Marks the node modified and refreshes visibility. */
        set(value) {
            deps.updateConfig(nodeData.id, prop.name, value);
        },

        /** Write a different config key (e.g. a code example setting `outputs`). */
        setConfig(key, value) {
            deps.updateConfig(nodeData.id, key, value);
        },

        /**
         * Change the node's output port count without writing an `outputs`
         * config value - what a rules editor needs, since its output count is
         * derived from the rule list.
         */
        setOutputCount(count) {
            deps.setOutputCount(nodeData.id, count);
        },

        /** Re-render the whole properties panel (remounts every editor). */
        rerender() {
            deps.rerender();
        },

        // Plain fetch: auth.js wraps window.fetch and adds X-API-Key for
        // /api/ URLs, so editors must not use anything else.
        api: {
            base: API_BASE,
            fetch: (...args) => fetch(...args),
        },

        toast: showToast,

        // Handles the plain-http LAN origins PyNode is usually reached on,
        // where navigator.clipboard does not exist.
        copyText,
    };
}
