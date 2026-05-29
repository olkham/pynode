# Plan: PyNode Repo Review & Improvements

PyNode is a well-architected Node-RED-style workflow app (Flask + vanilla JS + auto-discovered node plugins). The core engine and plugin model are clean and genuinely extensible. The main gaps are **security hardening, error-handling consistency, thread-safety, and the absence of tests**.

Items below are ordered from **easiest / smallest / least disruptive** to **most effort / most disruptive (potential breaking changes)**. Each is tagged with effort and a backwards-compatibility (BC) note.

## Tier 1 — Trivial, non-breaking (quick wins)
1. **Remove dead/commented code** — `pynode/server.py#L1386`, `pynode/workflow_engine.py#L177`, `pynode/nodes/InferenceNode/InferenceEngine/result_converters.py#L85`. *Effort: trivial. BC: none.*
2. **Fix bare `except:` clauses (17)** — change to `except Exception as e:` + log; behavior preserved, just surfaces errors. e.g. `pynode/server.py#L600`, `pynode/nodes/SwitchNode/switch_node.py#L114`, `pynode/nodes/mDNSNode/mdns_manager.py#L98`. *Effort: small. BC: none.*
3. **Container hardening** — add non-root `USER` to `Dockerfile`/`Dockerfile.cpu`; add `healthcheck`, resource limits, and log rotation in `docker-compose.yml`. *Effort: small. BC: none for API (watch file-mount permissions with non-root).*

## Tier 2 — Small, low-risk
4. **`print()` → `logging`** — single `logging` setup; replace prints in `pynode/main.py`, `pynode/server.py`. *Effort: small–medium. BC: none (only output format changes).*
5. **Debug broadcast polling** — skip/idle the worker when no SSE clients are connected (`pynode/server.py#L362`). *Effort: small. BC: none (internal).*
6. **Port inconsistency** — default is **500** in `pynode/main.py#L38` but README/`docker-compose.yml` say **5000**. *Effort: trivial. BC: changing the default IS a behavior change — safest fix is to align docs/compose to 500, or change default to 5000 and note it in release notes.*

## Tier 3 — Moderate, mostly non-breaking
7. **Thread-safety** — guard global dicts `_workflows`, `_working_engines`, `_deployed_engines` and debug-broadcast globals (`pynode/server.py#L26`) with consistent locking. *Effort: medium. BC: none (internal correctness).*
8. **Path traversal hardening** — resolve + confine file paths to a base dir in `pynode/nodes/MessageWriterNode/messagewriter_node.py`, `messagereader_node.py`, and upload route `pynode/server.py#L1299`. *Effort: medium. BC: minor — workflows relying on absolute/`..` paths would break (intended).*
9. **Bootstrap `pytest` suite** — cover engine, node registration, serialization. *Effort: medium (additive). BC: none.*
10. **Dedup route registration** — unify `_register_json_route` / `_register_file_upload_route` / `_register_stream_route`. *Effort: medium. BC: none if external behavior preserved.*

## Tier 4 — Larger effort, opt-in (BC-safe if defaulted off)
11. **`pickle.load()` on user files** — `pynode/nodes/MessageWriterNode/messagereader_node.py#L486` is an RCE vector. Gate behind explicit opt-in flag. *Effort: medium. BC: breaks existing pickle workflows unless opt-in defaults preserve current behavior.*
12. **Restrict `CORS`** — `pynode/server.py#L25` is fully open. Make allowed origins configurable. *Effort: medium. BC: keep open by default to preserve current UX; opt-in restriction.*
13. **Optional API authentication** — ~40 routes in `pynode/server.py` have zero auth and bind to `0.0.0.0`. Add optional API-key middleware. *Effort: medium–large. BC: none if disabled by default.*

## Tier 5 — Most effort / most disruptive
14. **Async / offloaded blocking I/O** — writer/reader nodes block their thread on file I/O. *Effort: large. BC: changes node execution timing/threading semantics.*
15. **Split `server.py` (~1400) & `base_node.py` (~900)** — separate routes/persistence/SSE; extract image/queue helpers. *Effort: large. BC: internal-only if public APIs preserved, but high churn/regression risk.*
16. **Parallel execution engine** — single `RLock` serializes all node ops; independent branches can't run concurrently. *Effort: largest. BC: significant — alters execution model and node ordering assumptions.*
17. **`exec()` sandboxing in FunctionNode** — `pynode/nodes/FunctionNode/function_node.py#L110`. This is a *designed* feature (like Node-RED); document as a trust boundary and tie to auth rather than hard-sandbox. *Effort: large if truly sandboxed. BC: sandboxing would break many existing function nodes.*

*Correction from the scan:* the "YOLO model reloaded per inference" claim is **false** — `pynode/nodes/UltralyticsNode/ultralytics_node.py#L171` lazy-loads and caches via `_model_loaded`.

## Further considerations (need input)
1. **Scope of work** — (A) just deliver this review, (B) implement the P0 security fixes, or (C) broader cleanup pass (P0–P2)?
2. **Auth model** — If we add auth: simple static API key, or something fuller (users/tokens)? Recommendation: optional API key, off by default to preserve current UX.
3. **Tests** — Bootstrap a `pytest` suite for the core engine as the foundation? Recommended as the first concrete step.
