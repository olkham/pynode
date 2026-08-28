// Properties editor for the Link nodes' `channel` property.
//
// A plain text input plus a <datalist> of channels already in use, so a user
// can pick an existing channel instead of retyping it. <datalist> never
// restricts input, so free-text entry keeps working.
//
// Suggestions are the union of:
//   - GET /api/link-channels, which scans every workflow's working engine, and
//   - channels typed into Link nodes in the editor right now, which the server
//     has not seen yet.

import { h, label } from '/js/node-ui/dom.js';

const LINK_NODE_TYPES = new Set(['LinkInNode', 'LinkOutNode']);

async function serverChannels(ctx) {
    try {
        const response = await ctx.api.fetch(`${ctx.api.base}/link-channels`);
        const data = await response.json();
        if (data && data.success && Array.isArray(data.channels)) return data.channels;
    } catch (error) {
        console.error('Failed to load link channels:', error);
    }
    return [];
}

function editorChannels(ctx) {
    const found = new Set();
    for (const node of ctx.allNodes()) {
        if (!LINK_NODE_TYPES.has(node.type)) continue;
        const channel = (node.config && node.config.channel != null ? String(node.config.channel) : '').trim();
        if (channel) found.add(channel);
    }
    return found;
}

export default {
    propertyType: 'link-channel',

    mount(ctx) {
        const listId = `link-channel-list-${ctx.nodeId}-${ctx.prop.name}`;

        return h('div', {},
            label(ctx.prop.label),
            h('input', {
                type: 'text',
                class: 'property-input',
                value: ctx.value !== undefined ? ctx.value : '',
                placeholder: ctx.prop.placeholder || ctx.prop.default || '',
                list: listId,
                onchange: e => ctx.set(e.target.value),
            }),
            // Populated by ready(); the input works with an empty list.
            h('datalist', { id: listId }),
        );
    },

    async ready(el, ctx) {
        const datalist = el.querySelector('datalist');
        if (!datalist) return;

        const merged = new Set([...await serverChannels(ctx), ...editorChannels(ctx)]);
        // The panel may have been re-rendered while the fetch was in flight.
        if (!datalist.isConnected) return;

        datalist.replaceChildren(
            ...[...merged].sort().map(channel => h('option', { value: channel })));
    },
};
