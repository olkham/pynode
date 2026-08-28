// Properties editor for ChangeNode's `changeRules` property (Node-RED style).
//
// Four rule types, each with its own row layout:
//   set     - write a typed value to a msg path
//   change  - search/replace inside a msg path
//   delete  - remove a msg path
//   move    - rename a msg path
//
// Every type also offers "is list" mode, where the path holds a list of
// objects and the rule applies to `key` inside every one of them (e.g.
// class_name on each detection).

import { h, iconButton, select } from '/js/node-ui/dom.js';

const RULE_TYPES = [
    { value: 'set', label: 'Set' },
    { value: 'change', label: 'Change' },
    { value: 'delete', label: 'Delete' },
    { value: 'move', label: 'Move' },
];

const VALUE_TYPES = [
    { value: 'str', label: 'string' },
    { value: 'num', label: 'number' },
    { value: 'bool', label: 'boolean' },
    { value: 'json', label: 'JSON' },
    { value: 'path', label: 'msg. path' },
    { value: 'date', label: 'timestamp' },
    { value: 'env', label: 'env var' },
];

const SEARCH_TYPES = [
    { value: 'str', label: 'string' },
    { value: 'regex', label: 'regex' },
];

const REPLACE_TYPES = [
    { value: 'str', label: 'string' },
    { value: 'path', label: 'msg. path' },
];

const rulesOf = ctx => ctx.value || [];

function update(ctx, index, field, value) {
    const rules = rulesOf(ctx);
    if (!rules[index]) return;
    rules[index][field] = value;
    ctx.set(rules);
    // The type picks the row layout, the value type picks the value input, and
    // list mode shows/hides the item key - all need a re-render.
    if (field === 'type' || field === 'valueType' || field === 'isList') ctx.rerender();
}

function add(ctx) {
    const rules = rulesOf(ctx);
    rules.push({ type: 'set', path: 'msg.payload', value: '', valueType: 'str' });
    ctx.set(rules);
    ctx.rerender();
}

function remove(ctx, index) {
    const rules = rulesOf(ctx);
    if (!rules.length) return;
    rules.splice(index, 1);
    ctx.set(rules);
    ctx.rerender();
}

function pathInput(ctx, index, rule, className = 'change-rule-path') {
    return h('input', {
        type: 'text',
        class: className,
        placeholder: 'msg.payload',
        value: rule.path || 'msg.payload',
        onchange: e => update(ctx, index, 'path', e.target.value),
    });
}

/** The "is list" toggle, plus the item key input once list mode is on. */
function listRow(ctx, index, rule, isList) {
    return h('div', { class: 'change-rule-row change-rule-list-row' },
        h('label', {
            class: 'change-rule-list-toggle',
            title: 'Apply this rule to every object in the list',
        },
            h('input', {
                type: 'checkbox',
                checked: isList,
                onchange: e => update(ctx, index, 'isList', e.target.checked),
            }),
            'is list',
        ),
        isList && h('span', { class: 'change-rule-to' }, 'key'),
        isList && h('input', {
            type: 'text',
            class: 'change-rule-key',
            placeholder: 'class_name',
            value: rule.key || '',
            onchange: e => update(ctx, index, 'key', e.target.value),
        }),
    );
}

function valueInput(ctx, index, rule) {
    const valueType = rule.valueType || 'str';
    const value = rule.value !== undefined ? rule.value : '';
    const onchange = e => update(ctx, index, 'value', e.target.value);

    if (valueType === 'bool') {
        const isTrue = value === true || value === 'true';
        return select(['true', 'false'], isTrue ? 'true' : 'false',
            newValue => update(ctx, index, 'value', newValue === 'true'), 'change-rule-value');
    }
    if (valueType === 'date') {
        // Generated when the rule runs; there is nothing to type.
        return h('input', { type: 'text', class: 'change-rule-value', disabled: true, placeholder: 'timestamp' });
    }
    if (valueType === 'json') {
        return h('input', {
            type: 'text',
            class: 'change-rule-value change-rule-json',
            placeholder: '{"key":"value"}',
            value,
            onchange,
        });
    }
    if (valueType === 'path') {
        return h('input', {
            type: 'text', class: 'change-rule-value', placeholder: 'payload.data', value, onchange,
        });
    }
    return h('input', {
        type: 'text',
        class: 'change-rule-value',
        placeholder: valueType === 'num' ? '0' : valueType === 'env' ? 'ENV_VAR' : '',
        value,
        onchange,
    });
}

function configRows(ctx, index, rule, ruleType, isList) {
    if (ruleType === 'set') {
        return [
            h('div', { class: 'change-rule-row' },
                pathInput(ctx, index, rule),
                h('span', { class: 'change-rule-to' }, 'to'),
                select(VALUE_TYPES, rule.valueType || 'str',
                    value => update(ctx, index, 'valueType', value), 'change-rule-value-type'),
                valueInput(ctx, index, rule),
            ),
            listRow(ctx, index, rule, isList),
        ];
    }

    if (ruleType === 'change') {
        return [
            h('div', { class: 'change-rule-row' },
                h('span', { class: 'change-rule-label' }, 'in'),
                pathInput(ctx, index, rule),
            ),
            listRow(ctx, index, rule, isList),
            h('div', { class: 'change-rule-row' },
                h('span', { class: 'change-rule-label' }, 'search'),
                select(SEARCH_TYPES, rule.searchType || 'str',
                    value => update(ctx, index, 'searchType', value), 'change-rule-search-type'),
                h('input', {
                    type: 'text',
                    class: 'change-rule-search',
                    placeholder: 'search',
                    value: rule.search || '',
                    onchange: e => update(ctx, index, 'search', e.target.value),
                }),
            ),
            h('div', { class: 'change-rule-row' },
                h('span', { class: 'change-rule-label' }, 'replace'),
                select(REPLACE_TYPES, rule.replaceType || 'str',
                    value => update(ctx, index, 'replaceType', value), 'change-rule-replace-type'),
                h('input', {
                    type: 'text',
                    class: 'change-rule-replace',
                    placeholder: 'replace',
                    value: rule.replace || '',
                    onchange: e => update(ctx, index, 'replace', e.target.value),
                }),
            ),
        ];
    }

    if (ruleType === 'delete') {
        return [
            h('div', { class: 'change-rule-row' }, pathInput(ctx, index, rule)),
            listRow(ctx, index, rule, isList),
        ];
    }

    if (ruleType === 'move') {
        return [
            h('div', { class: 'change-rule-row' },
                pathInput(ctx, index, rule),
                h('span', { class: 'change-rule-to' }, 'to'),
                h('input', {
                    type: 'text',
                    class: 'change-rule-to-path',
                    // In list mode the destination is a key inside each item,
                    // not a msg path.
                    placeholder: isList ? 'new_key' : 'msg.newPayload',
                    value: rule.toPath || '',
                    onchange: e => update(ctx, index, 'toPath', e.target.value),
                }),
            ),
            listRow(ctx, index, rule, isList),
        ];
    }

    return [];
}

function ruleItem(ctx, rule, index) {
    const ruleType = rule.type || 'set';
    const isList = rule.isList === true || rule.isList === 'true';

    return h('div', { class: 'change-rule-item', dataset: { ruleIndex: index } },
        h('div', { class: 'change-rule-header' },
            select(RULE_TYPES, ruleType,
                value => update(ctx, index, 'type', value), 'change-rule-type'),
            iconButton('✕', 'Delete rule', () => remove(ctx, index)),
        ),
        h('div', { class: 'change-rule-config' },
            ...configRows(ctx, index, rule, ruleType, isList),
        ),
    );
}

export default {
    propertyType: 'changeRules',

    mount(ctx) {
        return h('div', { class: 'change-rules-editor' },
            ...rulesOf(ctx).map((rule, index) => ruleItem(ctx, rule, index)),
            h('button', {
                class: 'btn btn-secondary btn-sm',
                type: 'button',
                onclick: () => add(ctx),
            }, '+ Add Rule'),
        );
    },
};
