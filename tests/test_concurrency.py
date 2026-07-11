"""Threaded stress test for Phase 2.2: _state_lock coverage.

One thread hammers full-deploy (/api/workflow/save) and restart while another
creates and deletes workflows. Before the locking fixes, the save/restart
routes iterated the module-global workflow dicts unlocked and could hit
KeyError / RuntimeError(dict changed size during iteration) - surfacing as
400/500 responses. The test asserts every request succeeds.

Hermeticity is critical here: each test gets a fresh app with its own
WorkflowManager (so runtime doesn't scale with workflows leaked by other test
modules), disk persistence is monkeypatched to a no-op on the manager
instance, and the worker threads honor a stop event that is always set (and
the threads joined) in a ``finally`` block BEFORE fixture teardown - so no
thread can outlive the app under test.
"""

import threading
import time

import pytest


@pytest.fixture
def stress_app(api_app, manager, monkeypatch):
    """The sandboxed per-test app with disk persistence disabled for speed."""
    monkeypatch.setattr(manager, 'save_workflow_to_disk', lambda: None)
    return api_app


@pytest.fixture
def stress_client(stress_app):
    with stress_app.test_client() as c:
        yield c


def test_save_restart_vs_create_delete_stress(stress_app, stress_client):
    # Guarantee at least one workflow always exists so DELETE never trips the
    # "cannot delete the last workflow" guard.
    resp = stress_client.post('/api/workflows', json={'name': 'stress base wf'})
    assert resp.status_code == 201

    iterations = 200
    time_budget = 8.0  # seconds; stop early rather than run long
    stop = threading.Event()
    failures = []
    errors = []

    def deployer():
        try:
            client = stress_app.test_client()
            for i in range(iterations):
                if stop.is_set():
                    break
                resp = client.post('/api/workflow/save')
                if resp.status_code != 200:
                    failures.append(
                        ('save', i, resp.status_code, resp.get_data(as_text=True)))
                resp = client.post('/api/workflow/restart')
                if resp.status_code != 200:
                    failures.append(
                        ('restart', i, resp.status_code, resp.get_data(as_text=True)))
        except Exception as e:  # pragma: no cover - defensive
            errors.append(('deployer', repr(e)))

    def churner():
        try:
            client = stress_app.test_client()
            for i in range(iterations):
                if stop.is_set():
                    break
                resp = client.post('/api/workflows', json={'name': f'stress wf {i}'})
                if resp.status_code != 201:
                    failures.append(
                        ('create', i, resp.status_code, resp.get_data(as_text=True)))
                    continue
                wid = resp.get_json()['id']
                resp = client.delete(f'/api/workflows/{wid}')
                if resp.status_code != 200:
                    failures.append(
                        ('delete', i, resp.status_code, resp.get_data(as_text=True)))
        except Exception as e:  # pragma: no cover - defensive
            errors.append(('churner', repr(e)))

    threads = [threading.Thread(target=deployer, daemon=True),
               threading.Thread(target=churner, daemon=True)]
    leaked = False
    try:
        for t in threads:
            t.start()
        deadline = time.monotonic() + time_budget
        for t in threads:
            t.join(timeout=max(0.0, deadline - time.monotonic()))
    finally:
        # Threads MUST be dead before the fixtures un-patch disk persistence,
        # or a leaked request could write to the real workflows directory.
        stop.set()
        for t in threads:
            t.join(timeout=30)
            if t.is_alive():
                leaked = True

    assert not leaked, 'stress thread failed to stop; aborting before teardown'
    assert errors == [], f'unhandled exceptions in threads: {errors}'
    assert failures == [], f'non-success responses under concurrency: {failures[:10]}'
