---
name: pynode-node-ui
description: Add or change custom editor UI for a PyNode node — a bespoke properties-panel control (rule list, picker, drawing tool, dropdown that writes another field) that the built-in property types cannot express. Use when asked to give a node a custom property editor, a custom widget/control in the properties panel, or to change an existing one; also when adding a new property `type` to a node's Python schema.
---

# Custom node UI in PyNode

A node type ships its own properties-panel editor **inside its own folder**.
Do not add a branch to `pynode/static/js/properties.js` — that file is a
generic engine now, and node-specific rendering does not live there.

The authoritative contract is
[pynode/static/js/node-ui/README.md](../../../pynode/static/js/node-ui/README.md).
This skill is the how-to for writing one.

## First: do you actually need a custom editor?

Check in this order.

1. **Is a built-in type enough?** `properties.js` renders these itself, and a
   node needs no UI file to use them:
   `text`, `password`, `number`, `checkbox`, `textarea`, `select`, `button`,
   `toggle`, `file`, `multiselect`, `hint`.
   Combined with `showIf` (conditional visibility) and `help`, these cover most
   nodes. Reach for them first.
2. **Would several unrelated nodes want this widget?** Then it is a built-in,
   not a node editor — add a branch to `properties.js` and list it above. (This
   is how `password` got added: `Qwen3VLMNode` declared it, nothing rendered it,
   and the field was invisible.)
3. **Is it specific to this node?** Then it is a node UI module. Continue.

## The three things you touch (all inside the node's folder)

```
pynode/nodes/MyNode/
├── my_node.py          # 1. the property schema  2. ui_assets declaration
└── ui/my-thing.js      # 3. the editor
```

### 1 + 2 — the Python side

```python
class MyNode(BaseNode):
    # Editor UI for this node's custom property type (see BaseNode.ui_assets).
    ui_assets = {'js': ['ui/my-thing.js']}     # 'css': [...] is also allowed

    properties = [
        {'name': 'thing', 'label': 'My Thing', 'type': 'myThing'},
    ]
```

The `type` string is the whole link between Python and JS. Paths are relative
to the node folder; anything that escapes it, does not exist, or is not
`.js`/`.css` is dropped with a warning at startup.

If a folder holds several node classes (`LinkNode`, `MQTTNode`, `Supervision`),
**each class that uses the property type declares `ui_assets` itself** — they
can share one file.

### 3 — the editor

```js
// Properties editor for MyNode's `myThing` property.
import { h, label } from '/js/node-ui/dom.js';

export default {
    propertyType: 'myThing',          // matches `type` in the Python schema

    mount(ctx) {                      // REQUIRED — build DOM, attach listeners
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

    ready(el, ctx) {},                        // optional — after insertion; may be async
    destroy(el, ctx) {},                      // optional — abort fetches, drop listeners
    onConfigChange(el, key, value, ctx) {},   // optional — another config key changed
};
```

Export an array to register more than one editor from one file.

Core renders the property group wrapper, `showIf` visibility and `prop.help`
around your element. It does **not** render a label — call `label()` yourself if
you want one (some editors, like the rule lists, deliberately have none).

## The context

`ctx` is the entire surface an editor gets.

| | |
|---|---|
| `ctx.nodeId`, `ctx.node` | the node being edited |
| `ctx.prop` | this property's schema entry, straight from Python |
| `ctx.value` | current value, falling back to the schema default |
| `ctx.set(value)` | write this property (marks modified, refreshes visibility) |
| `ctx.getConfig(key)` / `ctx.setConfig(key, value)` | read/write another key on this node |
| `ctx.allNodes()` | every node in the editor, read-only (for sibling-aware pickers) |
| `ctx.setOutputCount(n)` | change output ports *without* writing an `outputs` value |
| `ctx.rerender()` | re-render the panel — remounts every editor |
| `ctx.api.base`, `ctx.api.fetch` | `/api` and the auth-wrapped `fetch` |
| `ctx.toast(msg, kind)`, `ctx.copyText(text)` | UI helpers |

`ctx.rerender()` is the normal way to reflect a structural change (a rule
added, a type switch that changes the row layout). It is cheap — call it rather
than hand-patching the DOM.

## DOM helpers (`/js/node-ui/dom.js`)

`h(tag, props, ...children)` · `label(text)` · `select(options, selected, onChange, className)` ·
`iconButton(glyph, title, onClick, className)` · `esc(str)`

`h()` sets `value`/`checked`/`disabled`/`selected` as DOM **properties**, so
escaping is not something you have to remember. `on*` props take listeners;
`class`, `style`, `dataset` take strings/objects; `null`/`undefined`/`false`
children are skipped, so `cond && element` works.

## Rules

- **Import from `/js/node-ui/` only** — `dom.js` for helpers, `services/` for
  shared machinery. Never `properties.js`, `nodes.js` or `state.js`: everything
  an editor may do goes through `ctx`. This is what prevents import cycles.
- **Build elements. Never concatenate HTML strings.**
- **No `window.*` handlers.** Attach real listeners.
- **No module-level state keyed by node id** unless it is genuinely session
  state (`FunctionNode/ui/code-examples.js` keeps an undo stack this way, and
  that is the only good reason seen so far).
- Style with the panel's existing classes (`property-input`, `property-select`,
  `btn btn-secondary btn-sm`, `btn-icon-sm`), or ship a `ui/*.css` in the same
  `ui_assets` declaration.

## Worked examples in the tree

Read the closest one before writing a new editor.

| File | Shows |
|---|---|
| `ImageViewerNode/ui/stream-url.js` | the minimum; a derived value, no config write |
| `LinkNode/ui/link-channel.js` | async `ready()`, `ctx.api.fetch`, `ctx.allNodes()` |
| `SwitchNode/ui/rules.js` | a list editor, `ctx.setOutputCount`, `ctx.rerender` |
| `InjectNode/ui/inject-props.js` | rows whose widget depends on a per-row type |
| `ChangeNode/ui/change-rules.js` | the big one: four layouts, nested mode toggle |
| `FunctionNode/ui/code-examples.js` | `onConfigChange` to re-sync from another key |
| `MQTTNode/ui/mqtt-service.js`, `Supervision/ui/geometry.js` | using a shared service |

## Shared services

`/js/node-ui/services/` holds machinery more than one node could want, which is
why it is not in any node's folder:

- `geometry-editor.js` — `openGeometryEditor({nodeId, geometryType, value, onSave})`,
  the draw-on-frame modal
- `mqtt-brokers.js` — `populateBrokerSelect(selectEl, currentId)` and
  `openMqttBrokerDialog({current, assign})`

If a second node needs machinery you wrote, move it here rather than importing
across node folders.

## Gotchas

- **Restart the server after editing a UI file.** Asset URLs carry the file's
  mtime and are served `immutable`; the URL only changes when the node-types
  cache is rebuilt at import.
- **Assets are served from `/node-ui/`, never under `/api/`.** The API-key guard
  only challenges `/api/`, and the `auth.js` wrapper that attaches `X-API-Key`
  wraps `window.fetch` — which `import()` and `<link>` do not go through. Moving
  this route under `/api/` 401s the whole editor for keyed deployments. There is
  a test that fails if anyone does.
- **A property type with no registered editor renders a loud red row** and logs
  a console error. If you see it: the module failed to import, or its
  `propertyType` does not match the Python `type`.
- `window.nodeUiRegistry()` in the browser console lists every registered type
  and the file it came from.

## On-card widgets are NOT this mechanism (yet)

Controls rendered on the node **card** on the canvas (`ui_component` /
`ui_component_config` — button, toggle, slider, transport controls, badges,
counters) still go through the old chain in
[pynode/static/js/nodes.js](../../../pynode/static/js/nodes.js), with their SSE
updaters in `debug.js` reaching for DOM ids by convention. Adding one still
means editing those global files. Migrating them is phase 4 of
`plan-node-ui-modules-2026-08-27.md`.

If asked for an on-card control, say so rather than looking for a registry that
does not exist yet.

## Verify before reporting done

**Python** — `python -m pytest tests/test_node_ui_assets.py -q`. It checks
declaration validation, traversal refusal, the API-key guard, and — the one
that catches you — that every node declaring a custom property type ships a
module registering `propertyType: '<that type>'`.

**Browser** — there is no JS test harness, so this is on you. Run an isolated
server (`python -m pynode.main --host 127.0.0.1 --port 5099 --data-dir <scratch>`
— **never** against the repo's real `workflows/`), then drive headless Edge
over CDP and call `renderProperties(fakeNode)` directly:

```js
const props = await import('./js/properties.js');
const st = await import('./js/state.js');
st.state.nodes.set('probe', {id: 'probe', type: 'MyNode', name: 'probe',
                             config: {/* realistic */}, enabled: true, x: 0, y: 0});
props.renderProperties(st.state.nodes.get('probe'));
```

Then assert: zero `.property-missing-editor` elements, every
`.property-editor-slot` has children, the controls you expect exist, and a
change event writes to `node.config`. Check the console is clean.
