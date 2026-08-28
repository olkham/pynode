# Node UI modules

A node type that needs a custom properties-panel editor ships that editor
itself, in its own folder, instead of adding a branch to `properties.js`.

Adding a node with a custom control touches only that node's folder.

## How it fits together

```
pynode/nodes/ChangeNode/
├── change_node.py          ui_assets = {'js': ['ui/change-rules.js']}
└── ui/change-rules.js      export default { propertyType: 'changeRules', mount(ctx) {...} }
```

1. `node_registry` validates each declared path at import time (must exist,
   resolve inside the declaring node's folder, be `.js`/`.css`) and records it
   in an exact-match URL → file map. Bad entries are dropped with a warning,
   never raised.
2. `/api/node-types` carries the resulting URLs as `uiAssets`.
3. `loader.js` imports every module before the first panel can render and hands
   each default export to `registry.js`.
4. `properties.js` renders the built-in property types itself and looks up
   everything else in the registry. A type with no registered editor renders a
   visible "no editor registered" row — silence is what let a declared-but-never-
   implemented type sit unnoticed before.

## Writing an editor

```js
import { h, label } from '/js/node-ui/dom.js';

export default {
    propertyType: 'myThing',          // matches `type` in the Python schema

    mount(ctx) {                      // required: build DOM, attach listeners
        return h('div', {},
            label(ctx.prop.label),
            h('input', {
                type: 'text',
                class: 'property-input',
                value: ctx.value ?? '',
                onchange: e => ctx.set(e.target.value),
            }),
        );
    },

    ready(el, ctx) {},                // optional: after insertion (async work)
    destroy(el, ctx) {},              // optional: abort fetches, drop listeners
    onConfigChange(el, key, value, ctx) {},   // optional: another key changed
};
```

A module may export an array to register more than one editor.

### The context

| | |
|---|---|
| `ctx.nodeId`, `ctx.node` | the node being edited |
| `ctx.prop` | this property's schema entry, straight from Python |
| `ctx.value` | current value, falling back to the schema default |
| `ctx.set(value)` | write this property (marks modified, refreshes visibility) |
| `ctx.getConfig(key)` / `ctx.setConfig(key, value)` | read/write another key |
| `ctx.allNodes()` | every node in the editor, read-only |
| `ctx.setOutputCount(n)` | change output ports without writing an `outputs` value |
| `ctx.rerender()` | re-render the panel (remounts every editor) |
| `ctx.api.base` / `ctx.api.fetch` | `/api` and the auth-wrapped `fetch` |
| `ctx.toast(msg, kind)`, `ctx.copyText(text)` | UI helpers |

### Rules

- **Import from `/js/node-ui/` only** — `dom.js` for helpers, `services/` for
  shared machinery. Never from `properties.js`, `nodes.js` or `state.js`:
  everything an editor may do goes through `ctx`, which is what keeps the
  dependency arrow pointing one way.
- **Build elements, don't concatenate HTML.** `h()` sets `value`/`checked` as
  DOM properties, so escaping is not something you have to remember.
- **No `window.*` handlers.** Attach real listeners; that is why `main.js` no
  longer grows with every node.
- Style with the panel's existing classes, or ship a `ui/*.css` in the same
  `ui_assets` declaration.

### Shared services

`services/` holds machinery several nodes could want, which is why it is not in
any one node's folder:

- `geometry-editor.js` — the draw-on-frame modal (`openGeometryEditor`)
- `mqtt-brokers.js` — the broker picker and manager dialog

## Built-in property types

`properties.js` renders these itself; a node does not need a UI module for them:

`text`, `password`, `number`, `checkbox`, `textarea`, `select`, `button`,
`toggle`, `file`, `multiselect`, `hint`.

## Debugging

`window.nodeUiRegistry()` in the console lists every registered property type
and the file it came from.

Asset URLs carry the file's mtime and are served `immutable`, so **restart the
server after editing a node's UI file** — the URL only changes when the
node-types cache is rebuilt.

## Tests

`tests/test_node_ui_assets.py` covers declaration validation, traversal
refusal, the payload, and — the important one — that `/node-ui/` stays
reachable when `PYNODE_API_KEY` is set. It also asserts that every node
declaring a custom property type ships an editor registering it.

Browser behaviour has no harness; verify by hand against an isolated server
(see the repo's frontend verification notes).
