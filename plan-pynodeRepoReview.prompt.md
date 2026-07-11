# Plan: PyNode Repo Review & Improvements (fresh take — 2026-07-10)

Re-reviewed the whole repo. Since the last review, threading locks were added to workflow state (`_state_lock`), a pytest suite was bootstrapped (21 tests, all passing), and prints were cleaned out of `server.py`. The core plugin architecture remains solid.

**What's still open / newly found**, ordered into phases. Each step is small enough to land and verify independently; every step has an explicit "Verify" gate. Work top-to-bottom — Phase 0 makes everything after it provable.

---

## Phase 0 — Foundation: make changes provable

### 0.1 Add CI (GitHub Actions)
Tests exist but nothing runs them. Add `.github/workflows/ci.yml`: on push/PR, set up Python 3.11, `pip install -e .[dev]`, run `pytest -q`. Add pyright as a second (non-blocking at first) job — a config already exists in `pyproject.toml`.
- **Verify:** push a branch, CI goes green; break a test intentionally in a scratch commit, CI goes red.

### 0.2 Unify dependency declarations
`pyproject.toml` declares only `flask, numpy, opencv-python`; `requirements.txt` adds `flask-cors, waitress, paho-mqtt, torch, ultralytics, supervision` with inconsistent pinning. The package as installed via `pip install -e .` can't even serve requests (`flask_cors` missing from pyproject).
- Move all runtime deps into `pyproject.toml`; put heavy ML deps behind extras: `pynode[vision]` (ultralytics/torch/supervision), `pynode[mqtt]`. Node auto-discovery already tolerates missing deps, so extras fit the architecture.
- Reduce `requirements.txt` to `-e .[vision,mqtt]` or delete it (update INSTALL.md/Docker accordingly).
- Fix `requires-python`: code targets 3.11 (pyright config says so); either test on 3.8 or raise the floor honestly.
- **Verify:** fresh venv → `pip install -e .[dev]` → `pytest` passes and `pynode` boots and serves the UI with no ImportError. Docker build still succeeds.

---

## Phase 1 — Security (small diffs, high value)

### 1.1 Path traversal in file upload — `pynode/server.py:1328`
`upload_subdir = request.form.get('directory', 'models')` is joined into the package dir unsanitized: `directory=../../..` writes anywhere on disk (filename is basename'd, the directory is not). Fix: resolve the joined path and require it to be inside an allowlisted base (`models/`, `uploads/`); reject otherwise with 400.
- **Verify:** new API test (Flask `test_client`): upload with `directory=../../evil` → 400 and no file written; upload with `directory=models` still succeeds.

### 1.2 Arbitrary method invocation — `pynode/server.py:1347` (`trigger_node_action`)
`POST /api/nodes/<node_id>/<action>` calls **any** callable attribute by name: `configure`, `on_stop`, `_start_worker`, `report_error`, … Fix like `api_routes`: nodes declare `actions = ['trigger', 'reset', ...]` as a class attribute; the route 404s for anything not declared.
- **Verify:** API tests: declared button action still works (e.g. InjectNode trigger); `POST /api/nodes/<id>/on_stop` and `/_start_worker` → 404. Grep frontend JS for every action name it posts and confirm each is declared.

### 1.3 Gate `pickle.load` — `pynode/nodes/MessageWriterNode/messagereader_node.py:486`
Still an RCE-on-file-read vector, and worse, auto-detect selects pickle for any `.pkl` extension. Add an `allow_pickle` checkbox config (default **off**); when off, reading pickle (explicit or auto-detected) raises a clear node error telling the user to enable it.
- **Verify:** unit test: node without opt-in reading a `.pkl` reports an error and returns nothing; with `allow_pickle=true` a round-trip written by MessageWriterNode loads.

### 1.4 Configurable CORS + optional API key
`CORS(app)` is wide open and ~40 unauthenticated routes bind to `0.0.0.0`. Keep current behavior as default (BC), but add: `--cors-origins` (default `*`), and `--api-key` / `PYNODE_API_KEY` enabling a simple `before_request` key check (SSE + static exempt or key via query param). Document FunctionNode's `exec()` as a *designed* trust boundary in README — auth is the mitigation, not sandboxing.
- **Verify:** API tests: with key configured, request without header → 401, with header → 200; without key configured everything works as today.

---

## Phase 2 — Correctness & robustness

### 2.1 Atomic workflow saves + prune backups
`save_workflow_to_disk` writes `workflow.json` in place (crash mid-write corrupts it) and creates a timestamped backup on **every** save — `workflows/_backups` already holds **153 files** and grows forever (`set_node_enabled` saves on every toggle). Fix: write to `workflow.json.tmp` then `os.replace`; prune backups to the newest N (e.g. 20).
- **Verify:** unit tests for save/load round-trip and for pruning (create >N fake backups, save, assert count == N). Manually toggle a node twice, confirm backup count stays bounded.

### 2.2 Finish `_state_lock` coverage
Several routes iterate/mutate `_workflows` and the engine dicts without the lock: `save_workflow` (`server.py:993`), `deploy_changes` (`:1030`), `restart_workflow` (`:1165`), `set_node_enabled` (`:857`), `get_node_enabled` (`:883`), `_find_deployed_node` (`:82`), `_get_workflow_id_from_request` (`:65`). A concurrent `DELETE /api/workflows/<id>` can race any of these (dict changed during iteration, KeyError on `_workflows[wid]`). Take snapshots under the lock, do slow work (engine stop/start, disk I/O) outside it.
- **Verify:** a threaded stress test: one thread loops deploy/save, another creates+deletes workflows; no exceptions in N iterations. Existing tests stay green.

### 2.3 Replace remaining `print()` with logging
139 `print(` calls remain under `pynode/` — including `workflow_engine.py` (`:152, :168, :215, :236, :377, :394`) despite the earlier cleanup commit. Sweep them to `logger.*`.
- **Verify:** `grep -rn "print(" pynode --include="*.py"` → 0 (or only deliberate CLI output); smoke-run the app, node errors appear in the log.

### 2.4 Standardize API error contract
Routes return a mix of `{'error': ...}` and `{'success': False, 'error': ...}`; malformed JSON bodies raise Flask's HTML 400/415 (many routes use `request.json` bare). Pick one envelope, add a JSON error handler for 400/404/405/500, and use `request.get_json(silent=True)` with explicit validation.
- **Verify:** API test posts invalid JSON to a few routes → JSON error body with consistent shape, never HTML.

### 2.5 Dead code & lifecycle sweep
- `workflow_loaded` global (`server.py:496`) is never used — delete.
- `debug_broadcast_running` is never set back to False; the SSE broadcast thread has no shutdown path. Acceptable as daemon, but make it explicit (comment or a stop hook).
- `get_nodes` (`server.py:758`) shadows the `nodes` module import — rename local.
- `BaseNode.to_dict` returns `self.config` by reference — return a copy.
- **Verify:** tests green; pyright clean on touched files.

---

## Phase 3 — Test expansion (locks in Phases 1–2)

### 3.1 Flask API test suite
Use `app.test_client()` with a temp `WORKFLOWS_DIR` (needs a small refactor so the path isn't baked at import — see 4.1, or monkeypatch for now). Cover: workflow CRUD + active switching + last-workflow-delete guard; node CRUD + position + enabled; connections; `deploy-changes` (add/modify/delete node paths); upload validation (1.1); action allowlist (1.2); auth (1.4).
- **Verify:** `pytest -q` green in CI; each Phase 1/2 fix has at least one test that fails on the pre-fix code.

### 3.2 BaseNode messaging tests
Cover the queueing semantics nothing currently tests: `drop_while_busy` drops when target busy, queue-full path reports error, per-recipient deep-copy isolation (mutating downstream msg doesn't affect siblings), worker start/stop join, `_get_nested_value`/`_set_nested_value` including `items[0]` indexing and `msg.` prefix.
- **Verify:** tests pass without sleeps/flakiness (use the `on_input_direct` sink pattern from `conftest.py`).

### 3.3 Import/export round-trip tests
Export → import → export is stable; unknown node type becomes a disabled placeholder and round-trips back to its original type/config (`workflow_engine.py:300-319`); system error node never exported.
- **Verify:** covered by asserts on the exported dicts.

---

## Phase 4 — Structure (do after tests exist, not before)

### 4.1 App factory + `WorkflowManager`
`server.py` builds everything at import time (module-level engines, dicts, route registration), which is why tests must monkeypatch. Introduce `create_app(config)` and move `_workflows/_working_engines/_deployed_engines/_active_workflow_id/_state_lock` into a `WorkflowManager` class (one instance on the app). This is the enabler for clean test isolation and the config work in 4.3.
- **Verify:** whole suite passes with each test getting a fresh app; `pynode` CLI unchanged.

### 4.2 Split `server.py` (~1400 lines) into blueprints
`workflows.py` (workflow CRUD/deploy), `nodes.py` (node CRUD + dynamic node routes), `services.py` (MQTT), `uploads.py`, `sse.py` (debug stream + broadcast worker). Pure move, no behavior change — the API tests from 3.1 are the safety net.
- **Verify:** full test suite green; manual smoke: UI loads, deploy works, debug sidebar streams.

### 4.3 Config file / env support
Consolidate host/port/CORS/API-key/data-dir into one config object (env vars `PYNODE_*` + CLI flags), replacing the scattered `BASE_DIR`-relative conventions. Note `WORKFLOWS_DIR` currently derives from the package's parent dir — wrong once pip-installed site-packages; default to CWD or `~/.pynode`.
- **Verify:** run with `PYNODE_DATA_DIR` pointing at a temp dir → workflows persist there; Docker compose still works.

### 4.4 Split `base_node.py` (~940 lines)
Extract `Info` → `info.py`, `MessageKeys` → `messages.py`, image encode/decode + `process_image` → `image_utils.py`. Keep re-exports from `base_node` so all 50+ node imports keep working.
- **Verify:** suite green; `from pynode.nodes.base_node import BaseNode, Info, MessageKeys, process_image` still works.

---

## Phase 5 — Larger bets (optional, decide later)

- **Per-node async/offloaded blocking I/O** for writer/reader nodes (changes timing semantics).
- **Parallel-branch execution** — each node already has its own worker thread + queue, so this is less urgent than the old plan implied; profile before investing.
- **Frontend modularization** — ~6k lines of vanilla JS in `static/`; only worth touching with a concrete UI goal.

---

## Suggested working order

Each numbered step is one PR-sized change: **0.1 → 0.2 → 1.1 → 1.2 → 1.3 → 2.1 → 2.2 → 2.3 → 2.4+2.5 → 3.x (can interleave with Phase 1–2 as regression tests) → 1.4 → 4.1 → 4.2 → 4.3 → 4.4**. 1.4 is sequenced after the test suite exists because auth touches every route.
