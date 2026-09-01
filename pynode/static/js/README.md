# PyNode Frontend Architecture

The frontend has been restructured into modular ES6 modules for better maintainability and organization.

## Directory Structure

```
static/
├── index.html              # Main HTML file
├── style.css               # All styles
└── js/                     # Modular JavaScript
    ├── auth.js             # Optional API-key support (classic script, loads first)
    ├── main.js             # Application entry point
    ├── config.js           # Configuration and constants
    ├── state.js            # State management
    ├── ui-utils.js         # UI utility functions
    ├── palette.js          # Node palette rendering
    ├── nodes.js            # Node creation and rendering
    ├── connections.js      # Connection management
    ├── link-path.js        # Connection line geometry
    ├── selection.js        # Node selection logic
    ├── clipboard.js        # Copy/cut/paste of nodes
    ├── history.js          # Undo/redo
    ├── viewport.js         # Pan/zoom
    ├── minimap.js          # Canvas minimap
    ├── properties.js       # Properties panel (generic engine)
    ├── workflow.js         # Workflow import/export/deploy
    ├── workflows.js        # Multi-workflow tabs
    ├── debug.js            # Debug panel and SSE
    ├── events.js           # Event handlers
    └── node-ui/            # Editor UI that node types ship themselves
        ├── README.md       # The contract - read this before adding one
        ├── registry.js     # propertyType -> editor
        ├── loader.js       # Imports each node's declared modules at startup
        ├── context.js      # The object handed to an editor
        ├── dom.js          # h() / esc() helpers (editors' only core import)
        └── services/       # Machinery shared by several nodes' editors
            ├── geometry-editor.js
            └── mqtt-brokers.js
```

## Module Overview

### `main.js` - Entry Point
- Initializes the application
- Exposes functions to window for inline event handlers
- Coordinates module loading

### `config.js` - Configuration
- API base URL
- Node categories definition
- Global constants

### `state.js` - State Management
- Central state object
- State modification functions
- Node ID generation

### `ui-utils.js` - UI Utilities
- Toast notifications
- Other UI helper functions

### `palette.js` - Node Palette
- Loads available node types from API
- Renders node palette by category
- Handles drag-and-drop initiation

### `nodes.js` - Node Management
- Node creation (client-side)
- Node rendering
- Node deletion
- Node drag-and-drop handling

### `connections.js` - Connection Management
- Connection creation and rendering
- Connection drawing (temp lines)
- Connection deletion
- Connection updates on node movement

### `link-path.js` - Connection Line Geometry
- The one place that decides what shape a link is drawn in
- A port of Node-RED's `generateLinkPath`, adapted to this editor's node metrics
- Forward links (target to the right) get a single curve
- Backward links between level ports (a feedback loop) detour below the nodes:
  down, straight across, back up
- Backward links between offset ports (nodes stacked vertically) get a shallow
  shoulder out of the output, a sweep through the midpoint and a shoulder back
  into the input, rather than cutting diagonally back over both nodes
- Used for both rendered connections and the line that follows the cursor
  while a connection is being dragged

### `selection.js` - Selection Logic
- Single and multi-node selection
- Selection box handling
- Deselection

### `properties.js` - Properties Panel
- A generic engine over the property schema each node class declares
- Renders the built-in property types (text, password, number, checkbox,
  textarea, select, button, toggle, file, multiselect, hint)
- Node config updates, enabled toggle, action triggers, `showIf` visibility
- Anything else is looked up in the node-UI registry, where the node's own
  module registered an editor for it - node-specific rendering does NOT live
  here

### `node-ui/` - Node-supplied editor UI
A node type that needs a custom editor ships it in its own folder
(`pynode/nodes/<Node>/ui/*.js`, declared via the class's `ui_assets`), served
from `/node-ui/` and imported at startup. See
[node-ui/README.md](node-ui/README.md) for the contract, the context object,
and the rules for writing one.

### `workflow.js` - Workflow Operations
- Load workflow from API
- Deploy workflow to backend
- Clear workflow
- Import/export JSON files

### `debug.js` - Debug Panel
- SSE connection for debug messages
- Image viewer updates via SSE
- Debug message display

### `events.js` - Event Handling
- Canvas event listeners
- Keyboard shortcuts
- Selection box logic
- Drag-and-drop handling

## Key Design Decisions

### ES6 Modules
- Clean imports/exports
- Better dependency management
- Tree-shaking potential
- Modern JavaScript practices

### Circular Dependency Prevention
- Dynamic imports used where needed (`import().then()`)
- Careful module organization
- Clear separation of concerns

### Window Globals
A few functions are exposed to `window` for the inline handlers in the
properties panel's remaining string-built rows:
- `updateNodeProperty()`
- `updateNodeConfig()`
- `triggerNodeAction()`
- `toggleGate()`

Node-supplied editors under `node-ui/` attach real listeners and need nothing
here, which is why this list no longer grows with every node. The on-card
widgets in `nodes.js` still use inline handlers.

## Benefits of New Structure

1. **Maintainability**: Each module has a single responsibility
2. **Testability**: Modules can be tested independently
3. **Reusability**: Functions are organized logically
4. **Scalability**: Easy to add new features in appropriate modules
5. **Readability**: ~100-300 lines per file instead of 1000+ lines
6. **Collaboration**: Multiple developers can work on different modules

## Migration Notes

- All functionality is preserved
- Module loading is automatic via `type="module"` in HTML
- `properties.js` no longer carries per-node editors; those moved into node
  folders (see `node-ui/`). On-card widgets (`nodes.js`'s `uiComponent` chain)
  and their SSE updaters in `debug.js` have NOT moved yet.

## Future Improvements

- Consider removing inline event handlers in favor of event delegation
- Add TypeScript for better type safety
- Implement unit tests for each module
- Add build step for production (minification, bundling)
- Consider state management library (Redux, MobX) if state grows more complex
