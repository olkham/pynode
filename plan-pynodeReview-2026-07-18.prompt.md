# PyNode Project Review Plan — 2026-07-18

Follow-up to the July 2026 overhaul (see `plan-pynodeRepoReview.prompt.md`). This plan captures
the full findings of the 2026-07-18 project review. Phases A–D are being executed now;
E–H are deferred and can be picked up in any later session.

Status legend: `[NOW]` in progress this session · `[LATER]` deferred · `[DECIDE]` needs a user decision.

---

## Phase A [NOW] — Quick bug fixes + compose port

1. **Dead `include_predictions` toggle** — `pynode/nodes/UltralyticsNode/ultralytics_node.py:348`
   reads `if include_predictions or True:` so the "Include Predictions in Output" checkbox does
   nothing. Honor the flag (use `get_config_bool` for string-safety; same for `include_image`).
2. **docker-compose port typo** — `docker-compose.yml` publishes `"500:5000"`; DOCKER.md documents
   port 5000. Change to `"5000:5000"`.
3. **Silent node-import failures** — `pynode/nodes/__init__.py` `_try_import_python_files` swallows
   every exception with bare `continue`; a custom node with a syntax error vanishes from the palette
   with no log output. Log warnings (missing optional deps may stay at debug level).
4. Minor cleanups: dead `system_error_node` variable in `workflow_engine.py:367`; ImageViewerNode
   MJPEG generator loops forever after node stop (holds a waitress thread); ImageViewerNode's shared
   `last_sent_timestamp` makes the SSE broadcaster and the `/frame` polling route steal frames from
   each other; `socket.inet_ntoa` in `mdns_manager.py` throws on IPv6 service records.

Acceptance: full test suite passes; toggling "Include Predictions" actually changes output;
node import errors appear in the log.

## Phase B [NOW] — Model / node storage directories

Problem: `YOLO('yolo26n.pt')` downloads weights into the process CWD and `export(format='openvino')`
writes next to the source; strays currently exist in 4 places (repo root, `models/`,
`pynode/models/`, `pynode/nodes/`). A pip-installed PyNode launched from inside a venv would scatter
files there. Also `[tool.setuptools.package-data] nodes/**/*` would bake a stray `.pt` in
`pynode/nodes/` into a locally built wheel.

1. `pynode/config.py`: add `PYNODE_MODELS_DIR` env var + `resolve_models_dir()` → default
   `<data_dir>/models/`; `--models-dir` CLI flag in `main.py` (mirror the `--data-dir` pattern).
2. `BaseNode.get_storage_dir(subdir=None)` → `<data_dir>/node_storage/<NodeType>/`, created lazily.
   General rule going forward: nodes never write binaries outside their storage dir.
3. UltralyticsNode: resolve bare model names to an absolute path under the models dir before calling
   `YOLO()` (Ultralytics downloads named assets to an absolute path; the OpenVINO export then lands
   in the same folder). Check legacy locations first to avoid re-downloading; never move/delete
   existing user files automatically (`pynode/models/` holds real user models).
4. Packaging: `[tool.setuptools.exclude-package-data]` for `*.pt` / `*_openvino_model` so strays
   can't enter wheels.
5. Document (README/INSTALL): env var, CLI flag, where models live per install type.

Deferred idea: settings UI for the models folder.

## Phase C [NOW] — mDNS in Docker: fix + docs

Root cause: default bridge network; mDNS is link-local multicast (224.0.0.251:5353) which Docker's
bridge/NAT does not forward. `HOST_IP` only fixes the advertised address, not reachability.

1. DOCKER.md: new "mDNS / service discovery" section — explain the limitation; document `HOST_IP`
   (currently undocumented); give options in order: `network_mode: host` (Linux; ports mapping
   ignored; does NOT help on Docker Desktop Win/Mac), macvlan, host-side avahi reflector
   (`enable-reflector=yes`) or mdns-repeater sidecar.
2. docker-compose.yml: commented-out `network_mode: host` alternative block with the caveats.
3. Advertised `service_port` must match the externally reachable port (relates to A2).

## Phase D [NOW] — send() copy semantics (biggest perf win)

`BaseNode.send()` deep-copies the message per recipient (`base_node.py:254`); raw numpy frames make
this ~6 MB memcpy per hop per recipient. Adopt Node-RED semantics: **last recipient gets the
original message, only additional wires get deep copies** — zero frame copies in the common
single-connection case. Contract change: *senders must not mutate a message after calling send().*

1. Audit every node for post-`send()` mutation and source nodes for numpy buffer reuse; fix
   offenders to create fresh messages instead.
2. Implement last-recipient-no-copy in both the queued path and the sink "direct processing" path.
3. Update/adjust tests that assert sender-side isolation; document the contract in base_node.py.

## Phase E [LATER] — Remaining performance items

- Sink "direct processing" runs on the sender's thread (ImageViewer JPEG encode inside the camera
  loop) and skips `drop_while_busy`; route sinks through the normal queue or apply drop checks.
- Idle worker threads busy-poll every 10–100 ms (`base_node.py:296`); switch to blocking
  `queue.get()` with a `None` sentinel pushed in `on_stop()`.
- `sort_msg_keys` runs on every send per recipient; sort at display time in DebugNode instead.
- Waitress `threads=10` (`main.py:103`): each SSE client and MJPEG viewer permanently holds a
  thread → silent API starvation. Make threads a CLI flag, default higher (~24), document.
- Dockerfile uses `cuda:12.6.0-devel` (~8 GB base); switch to `-runtime` or multi-stage.

## Phase F [LATER] — UI/UX

- Canvas node search (Ctrl+F: find by name/type, pan to node).
- Per-node runtime status text on canvas (Node-RED `status()` equivalent: "model loaded", fps,
  drop count) — SSE plumbing (`sse_handlers`) already exists.
- Palette manager UI (falls out of Phase G).
- Light theme (style.css is dark-only; tokenize colors to CSS variables first).
- Groups/subflows — biggest structural gap vs Node-RED; affects workflow JSON schema, decide
  deliberately before other schema work.

## Phase G [LATER] — Live node install from an approved registry

Constraints today: registries built once at import (`node_registry.py:154-156`); node `api_routes`
registered as real Flask routes at app creation (`api/nodes.py:418`, frozen after first request).

1. **Registry**: curated JSON index in a separate GitHub repo (`pynode-registry`), served raw:
   name, description, pip requirement/git URL, version, author, category, `verified` flag.
   Approval = PR review.
2. **External nodes dir**: also scan `<data_dir>/nodes/` (Node-RED `~/.node-red` pattern) —
   cheap, enables "drop a folder in, restart". Later: `[project.entry-points."pynode.nodes"]`.
3. **API**: `GET /api/palette/catalog` (cached), `POST /api/palette/install` (pip via
   `sys.executable -m pip`, reuse install_nodes.py pattern), `DELETE` for removal.
4. **Activation v1**: install + "restart to activate" banner.
   **v2 (hot reload)**: make cache builders re-runnable, `palette-updated` SSE event, convert
   per-node API routes to one catch-all `/api/nodes/<node_id>/<path:sub>` dispatching through the
   registry dict at request time (removes the Flask route-freeze problem).
5. **Security**: only names from the curated index, pinned versions, behind the API key. Never
   accept arbitrary pip specs from the UI.

## Phase H [DECIDE] — Naming

- **GitHub repo rename** `olkham/pynode` → `olkham/pynode-flow`: recommended; cheap, GitHub
  redirects, removes PyPI/repo mismatch. Update `[project.urls]`, README.
- **Import package rename** (`pynode` → `pynode_flow`): argument for = the unrelated PyPI `pynode`
  0.1.0 namespace-collision trap (see 2026-07-18 incident); argument against = breaks all imports
  and custom nodes; mismatched dist/import names are normal (opencv-python/cv2).
  Recommendation: keep `pynode` import; add a startup guard that detects the conflicting `pynode`
  dist (importlib.metadata) and fails loudly with "uninstall the unrelated pynode package".
  If ever renaming, the pre-1.0 window is the only sane time.

---

## Execution notes (any session picking this up)

- User commits phases themselves; do not commit.
- Test safety (hard rules, see memory `pynode-test-safety-incident`): tests must build apps via
  `create_app` with tmp paths (tests/conftest.py `api_client`); join every thread before fixture
  teardown; after test work verify `git status --porcelain -- workflows/` is empty. A live PyNode
  server may be running against this repo — its own saves to workflows/ are not test leakage.
- Suite size at time of writing: 306 tests.
