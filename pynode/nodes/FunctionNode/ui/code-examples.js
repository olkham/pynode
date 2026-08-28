// Properties editor for FunctionNode's `code-examples` dropdown.
//
// A dropdown of ready-made snippets. Picking one drops its code into the
// target textarea (prop.target) instead of storing a config value of its own.
//
// The selection is DERIVED from the target's current code, not stored: code
// matching an example keeps that example's name showing, and editing the code
// by hand switches the dropdown to "Custom" (see onConfigChange).
//
// An example may also declare `outputs`, which is applied to the node's output
// count so a two-output template really gives the node two outputs.

import { h, label } from '/js/node-ui/dom.js';

// One-step undo: nodeId -> what applying the example replaced
// ({target, code, outputs?}). Session-only and deliberately not persisted - it
// exists so an accidental template pick cannot silently eat hand-written code.
// Applying another example overwrites the entry, so only the most recent
// replacement can be restored.
const undoStack = new Map();

const codeOf = (ctx, key) => `${ctx.getConfig(key) !== undefined ? ctx.getConfig(key) : ''}`;

/** Re-derive the dropdown's selection from the target's current code. */
function syncSelection(select, ctx) {
    const code = codeOf(ctx, ctx.prop.target);
    let value = code.trim() === '' ? '' : '__custom__';
    for (const option of select.options) {
        if (option.dataset.code !== undefined && option.dataset.code === code) {
            value = option.value;
            break;
        }
    }
    select.value = value;
}

function apply(select, ctx) {
    const option = select.options[select.selectedIndex];
    // Placeholder or the (disabled) "Custom" entry: nothing to apply.
    if (!option || !option.value || option.value === '__custom__') {
        syncSelection(select, ctx);
        return;
    }

    const target = ctx.prop.target;
    const code = option.dataset.code || '';
    const outputs = option.dataset.outputs;

    // Remember what this example replaces so the undo button can restore it.
    const undoEntry = { target, code: codeOf(ctx, target) };
    if (outputs !== undefined) {
        // Only track outputs when the example actually changes it. An unset
        // count restores to 1, the node's default.
        const current = ctx.getConfig('outputs');
        undoEntry.outputs = current !== undefined ? current : 1;
    }
    undoStack.set(ctx.nodeId, undoEntry);

    ctx.setConfig(target, code);
    if (outputs !== undefined) {
        ctx.setConfig('outputs', parseInt(outputs, 10));
    }

    // Re-render so the textarea shows the new code, the Outputs field shows
    // the new count, and the undo button becomes enabled.
    ctx.rerender();
}

function undo(ctx) {
    const entry = undoStack.get(ctx.nodeId);
    if (!entry) return;

    undoStack.delete(ctx.nodeId);
    ctx.setConfig(entry.target, entry.code);
    if (entry.outputs !== undefined) {
        ctx.setConfig('outputs', entry.outputs);
    }

    ctx.rerender();
    ctx.toast('Restored the previous code');
}

export default {
    propertyType: 'code-examples',

    mount(ctx) {
        const options = Array.isArray(ctx.prop.options) ? ctx.prop.options : [];
        const currentCode = codeOf(ctx, ctx.prop.target);
        const matchIndex = options.findIndex(example => example.code === currentCode);
        const isCustom = currentCode.trim() !== '' && matchIndex === -1;
        const canUndo = undoStack.has(ctx.nodeId);

        const select = h('select', {
            class: 'property-select property-example-select',
            onchange: () => apply(select, ctx),
        },
            h('option', { value: '', selected: !isCustom && matchIndex === -1 }, '— Select an example… —'),
            h('option', { value: '__custom__', disabled: true, selected: isCustom }, 'Custom'),
            ...options.map((example, i) => h('option', {
                value: String(i),
                selected: i === matchIndex,
                dataset: example.outputs !== undefined
                    ? { code: example.code, outputs: example.outputs }
                    : { code: example.code },
            }, example.label)),
        );

        return h('div', {},
            label(ctx.prop.label),
            h('div', { class: 'property-example-container' },
                select,
                h('button', {
                    class: 'btn btn-secondary property-example-undo',
                    type: 'button',
                    disabled: !canUndo,
                    title: canUndo ? 'Undo - restore the code this example replaced' : 'Nothing to undo',
                    onclick: () => undo(ctx),
                }, '↶'),
            ),
        );
    },

    // Editing the code by hand has to switch the dropdown to "Custom", and
    // typing an example's code back in has to re-select that example.
    onConfigChange(el, key, value, ctx) {
        if (key !== ctx.prop.target) return;
        syncSelection(el.querySelector('select'), ctx);
    },
};
