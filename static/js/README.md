# PyNode Frontend Architecture

The frontend has been restructured into modular ES6 modules for better maintainability and organization.

## Directory Structure

```
static/
├── index.html              # Main HTML file
├── style.css               # All styles
├── app.js                  # Legacy monolithic file (can be removed)
└── js/                     # Modular JavaScript
    ├── main.js             # Application entry point
    ├── config.js           # Configuration and constants
    ├── state.js            # State management
    ├── ui-utils.js         # UI utility functions
    ├── palette.js          # Node palette rendering
    ├── nodes.js            # Node creation and rendering
    ├── connections.js      # Connection management
    ├── selection.js        # Node selection logic
    ├── properties.js       # Properties panel
    ├── workflow.js         # Workflow import/export/deploy
    ├── debug.js            # Debug panel and SSE
    └── events.js           # Event handlers
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

### `selection.js` - Selection Logic
- Single and multi-node selection
- Selection box handling
- Deselection

### `properties.js` - Properties Panel
- Property panel rendering
- Node property updates
- Node config updates
- Gate toggle (special case)
- Action triggers (inject, etc.)

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
Some functions are exposed to `window` for inline event handlers in dynamically generated HTML:
- `updateNodeProperty()`
- `updateNodeConfig()`
- `triggerNodeAction()`
- `toggleGate()`

This is necessary because the properties panel HTML is generated dynamically with inline `onchange` handlers.

## Benefits of New Structure

1. **Maintainability**: Each module has a single responsibility
2. **Testability**: Modules can be tested independently
3. **Reusability**: Functions are organized logically
4. **Scalability**: Easy to add new features in appropriate modules
5. **Readability**: ~100-300 lines per file instead of 1000+ lines
6. **Collaboration**: Multiple developers can work on different modules

## Migration Notes

- The old `app.js` is no longer used
- All functionality is preserved
- No API changes required
- Works with existing backend
- Module loading is automatic via `type="module"` in HTML

## Future Improvements

- Consider removing inline event handlers in favor of event delegation
- Add TypeScript for better type safety
- Implement unit tests for each module
- Add build step for production (minification, bundling)
- Consider state management library (Redux, MobX) if state grows more complex
