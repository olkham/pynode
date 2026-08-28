// Properties editor for ImageViewerNode's `streamUrl` property.
//
// Not a config value at all: it derives the node's MJPEG stream URL and offers
// ways to get at it (open in a tab, copy to the clipboard).

import { h, label } from '/js/node-ui/dom.js';

export default {
    propertyType: 'streamUrl',

    mount(ctx) {
        const streamUrl = `${window.location.origin}/api/nodes/${ctx.nodeId}/stream`;

        const field = h('input', {
            type: 'text',
            class: 'property-input property-stream-url',
            value: streamUrl,
            readOnly: true,
            onclick: e => e.target.select(),
        });

        return h('div', {},
            label(ctx.prop.label),
            h('div', { class: 'property-stream-url-container' },
                field,
                h('button', {
                    class: 'btn btn-secondary property-stream-btn',
                    type: 'button',
                    title: 'Open stream in new tab',
                    onclick: () => window.open(streamUrl, '_blank'),
                }, '↗️'),
                h('button', {
                    class: 'btn btn-secondary property-stream-btn',
                    type: 'button',
                    title: 'Copy URL',
                    onclick: async () => {
                        const ok = await ctx.copyText(streamUrl);
                        ctx.toast(ok ? 'URL copied!' : 'Could not copy the URL', ok ? 'info' : 'error');
                    },
                }, '🗐'),
            ),
        );
    },
};
