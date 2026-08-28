// DOM helpers for node UI modules.
//
// The properties panel used to be assembled as one big HTML string with inline
// `onchange="window.foo(...)"` handlers, which forced every editor callback
// onto `window` and meant every interpolated value had to remember to escape
// itself (several branches did not - a `"` in a node name broke the panel).
// Editors build real elements with real listeners instead, and `h()` sets
// values as PROPERTIES, so escaping is not a thing an editor author has to
// think about.
//
// This is the only core module a node's UI file may import.

/**
 * Escape a value for interpolation into HTML.
 * Still needed by the core panel's remaining string-built rows; editors that
 * use h() do not need it.
 */
export function esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function append(el, children) {
    for (const child of children) {
        if (child === null || child === undefined || child === false) continue;
        if (Array.isArray(child)) {
            append(el, child);
        } else if (child instanceof Node) {
            el.appendChild(child);
        } else {
            el.appendChild(document.createTextNode(String(child)));
        }
    }
}

// Set as a DOM property rather than an attribute: attributes need escaping and
// (for value/checked) only seed the initial state.
const PROPERTIES = new Set(['value', 'checked', 'selected', 'disabled', 'readOnly', 'textContent']);

/**
 * Build an element.
 *
 *   h('input', {type: 'text', value: cfg.name, onchange: e => ctx.set(e.target.value)})
 *   h('div', {class: 'rule-row'}, label, input, deleteButton)
 *
 * Props: `class`, `style` and `dataset` take objects or strings; `on*` takes a
 * listener; null/undefined/false values are skipped so `cond && value` works.
 */
export function h(tag, props, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') {
            el.className = value;
        } else if (key === 'style' || key === 'dataset') {
            Object.assign(el[key], value);
        } else if (key.startsWith('on') && typeof value === 'function') {
            el.addEventListener(key.slice(2).toLowerCase(), value);
        } else if (PROPERTIES.has(key)) {
            el[key] = value;
        } else {
            el.setAttribute(key, value);
        }
    }
    append(el, children);
    return el;
}

/** The panel's standard property label. */
export function label(text) {
    return h('label', { class: 'property-label' }, text);
}

/**
 * A <select> built from [{value, label}] (or plain strings), with `selected`
 * pre-chosen and `onChange` receiving the new value.
 */
export function select(options, selected, onChange, className = 'property-select') {
    const el = h('select', { class: className, onchange: e => onChange(e.target.value) });
    for (const option of options) {
        const value = typeof option === 'object' ? option.value : option;
        const text = typeof option === 'object' ? option.label : option;
        el.appendChild(h('option', { value, selected: value === selected }, text));
    }
    return el;
}

/** The panel's small square icon button (delete a rule, undo, ...). */
export function iconButton(glyph, title, onClick, className = 'btn-icon-sm') {
    return h('button', { class: className, type: 'button', title, onclick: onClick }, glyph);
}
