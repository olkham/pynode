// Properties editor for InjectNode's `injectProps` property.
//
// A list of "msg.<path> = <typed value>" rows describing what the node injects.
// The value input's shape follows the chosen type, so changing the type
// re-renders the row.

import { h, iconButton, select } from '/js/node-ui/dom.js';

// The icon doubles as the collapsed label once a type is chosen, which is why
// the option text differs for the selected entry.
const VALUE_TYPES = [
    { value: 'str', icon: 'az', label: 'string' },
    { value: 'num', icon: '123', label: 'number' },
    { value: 'bool', icon: 't/f', label: 'boolean' },
    { value: 'json', icon: '{ }', label: 'JSON' },
    { value: 'date', icon: '⏱', label: 'timestamp' },
    { value: 'env', icon: 'env', label: 'env variable' },
];

const propsOf = ctx => ctx.value || [];

function update(ctx, index, field, value) {
    const props = propsOf(ctx);
    if (!props[index]) return;
    props[index][field] = value;
    ctx.set(props);
    // The value input depends on the type, so that one needs a re-render.
    if (field === 'valueType') ctx.rerender();
}

function add(ctx) {
    const props = propsOf(ctx);
    props.push({ property: 'payload', valueType: 'date', value: '' });
    ctx.set(props);
    ctx.rerender();
}

function remove(ctx, index) {
    const props = propsOf(ctx);
    if (!props.length) return;
    props.splice(index, 1);
    ctx.set(props);
    ctx.rerender();
}

function typeSelect(ctx, index, selected) {
    const el = h('select', {
        class: 'inject-prop-type',
        onchange: e => update(ctx, index, 'valueType', e.target.value),
    });
    for (const type of VALUE_TYPES) {
        const isSelected = type.value === selected;
        el.appendChild(h('option', {
            value: type.value,
            selected: isSelected,
            dataset: { icon: type.icon },
        }, isSelected ? type.icon : type.label));
    }
    return el;
}

function valueInput(ctx, index, prop) {
    const valueType = prop.valueType || 'str';
    const value = prop.value !== undefined ? prop.value : '';
    const onchange = e => update(ctx, index, 'value', e.target.value);

    if (valueType === 'date') {
        // The timestamp is generated at inject time; there is nothing to type.
        return h('input', { type: 'text', class: 'inject-prop-value', disabled: true, placeholder: 'timestamp' });
    }
    if (valueType === 'bool') {
        return select(['true', 'false'], value === true ? 'true' : value === false ? 'false' : String(value),
            newValue => update(ctx, index, 'value', newValue), 'inject-prop-value');
    }
    if (valueType === 'json') {
        return h('input', {
            type: 'text',
            class: 'inject-prop-value inject-prop-json',
            placeholder: '{"key":"value"}',
            value,
            onchange,
        });
    }
    return h('input', {
        type: 'text',
        class: 'inject-prop-value',
        placeholder: valueType === 'num' ? '0' : valueType === 'env' ? 'ENV_VAR' : '',
        value,
        onchange,
    });
}

function propRow(ctx, prop, index) {
    return h('div', { class: 'inject-prop-row', dataset: { propIndex: index } },
        h('span', { class: 'inject-prop-prefix' }, 'msg.'),
        h('input', {
            type: 'text',
            class: 'inject-prop-key',
            placeholder: 'payload',
            value: prop.property || '',
            onchange: e => update(ctx, index, 'property', e.target.value),
        }),
        h('span', { class: 'inject-prop-eq' }, '='),
        typeSelect(ctx, index, prop.valueType || 'str'),
        valueInput(ctx, index, prop),
        iconButton('✕', 'Delete', () => remove(ctx, index)),
    );
}

export default {
    propertyType: 'injectProps',

    mount(ctx) {
        return h('div', { class: 'inject-props-editor' },
            ...propsOf(ctx).map((prop, index) => propRow(ctx, prop, index)),
            h('button', {
                class: 'btn btn-secondary btn-sm',
                type: 'button',
                onclick: () => add(ctx),
            }, '+ Add'),
        );
    },
};
