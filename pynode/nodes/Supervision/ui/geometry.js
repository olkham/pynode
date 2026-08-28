// Properties editor for the Supervision nodes' `geometry` property
// (SV Line Counter's line, SV Polygon Zone's polygon).
//
// A text field holding the serialized geometry, plus a button that opens the
// shared draw-on-frame modal so the user can place it on the node's own latest
// frame instead of typing coordinates.

import { h, label } from '/js/node-ui/dom.js';
import { openGeometryEditor } from '/js/node-ui/services/geometry-editor.js';

export default {
    propertyType: 'geometry',

    mount(ctx) {
        const geometryType = ctx.prop.geometryType || 'polygon';

        const field = h('input', {
            type: 'text',
            class: 'property-input property-geometry-input',
            value: ctx.value !== undefined ? ctx.value : '',
            onchange: e => ctx.set(e.target.value),
        });

        return h('div', {},
            label(ctx.prop.label),
            h('div', { class: 'property-geometry-container' },
                field,
                h('button', {
                    class: 'btn btn-secondary property-geometry-btn',
                    type: 'button',
                    title: `Draw the ${geometryType} on the node's latest frame`,
                    onclick: () => openGeometryEditor({
                        nodeId: ctx.nodeId,
                        geometryType,
                        value: ctx.value,
                        onSave: value => {
                            ctx.set(value);
                            // The panel is not re-rendered, so keep the field
                            // showing what was just drawn.
                            field.value = value;
                        },
                    }),
                }, '✏ Draw on frame'),
            ),
        );
    },
};
