// Properties editor for SwitchNode's `rules` property.
//
// One rule per output: rule N routes to output N, so adding or removing a rule
// changes the node's output port count.

import { h, iconButton, select } from '/js/node-ui/dom.js';

const OPERATORS = [
    { value: 'eq', label: '==' },
    { value: 'neq', label: '!=' },
    { value: 'lt', label: '<' },
    { value: 'lte', label: '<=' },
    { value: 'gt', label: '>' },
    { value: 'gte', label: '>=' },
    { value: 'between', label: 'between' },
    { value: 'contains', label: 'contains' },
    { value: 'matches', label: 'matches regex' },
    { value: 'true', label: 'is true' },
    { value: 'false', label: 'is false' },
    { value: 'null', label: 'is null' },
    { value: 'nnull', label: 'is not null' },
    { value: 'empty', label: 'is empty' },
    { value: 'nempty', label: 'is not empty' },
    { value: 'haskey', label: 'has key' },
    { value: 'else', label: 'otherwise' },
];

const VALUE_TYPES = [
    { value: 'str', label: 'string' },
    { value: 'num', label: 'number' },
    { value: 'bool', label: 'boolean' },
    { value: 'json', label: 'JSON' },
];

const rulesOf = ctx => ctx.value || [];

function update(ctx, index, field, value) {
    const rules = rulesOf(ctx);
    if (!rules[index]) return;
    rules[index][field] = value;
    ctx.set(rules);
}

function add(ctx) {
    const rules = rulesOf(ctx);
    rules.push({ operator: 'eq', value: '', valueType: 'str' });
    ctx.set(rules);
    ctx.setOutputCount(rules.length);
    ctx.rerender();
}

function remove(ctx, index) {
    const rules = rulesOf(ctx);
    // The node always keeps at least one rule/output.
    if (rules.length <= 1) return;
    rules.splice(index, 1);
    ctx.set(rules);
    ctx.setOutputCount(rules.length);
    ctx.rerender();
}

function ruleItem(ctx, rule, index) {
    return h('div', { class: 'rule-item', dataset: { ruleIndex: index } },
        h('div', { class: 'rule-header' },
            h('span', { class: 'rule-label' }, `Rule ${index + 1} → Output ${index + 1}`),
            iconButton('✕', 'Delete rule', () => remove(ctx, index), 'btn-icon'),
        ),
        h('div', { class: 'rule-config' },
            select(OPERATORS, rule.operator || 'eq',
                value => update(ctx, index, 'operator', value), 'rule-operator'),
            h('input', {
                type: 'text',
                class: 'rule-value',
                placeholder: 'Value',
                value: rule.value || '',
                onchange: e => update(ctx, index, 'value', e.target.value),
            }),
            select(VALUE_TYPES, rule.valueType || 'str',
                value => update(ctx, index, 'valueType', value), 'rule-type'),
        ),
    );
}

export default {
    propertyType: 'rules',

    mount(ctx) {
        return h('div', { class: 'rules-editor' },
            ...rulesOf(ctx).map((rule, index) => ruleItem(ctx, rule, index)),
            h('button', {
                class: 'btn btn-secondary btn-sm',
                type: 'button',
                onclick: () => add(ctx),
            }, '+ Add Rule'),
        );
    },
};
