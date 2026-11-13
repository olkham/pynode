"""Tests for the production-readiness features.

- health endpoints (``/healthz`` liveness, ``/api/health`` detail)
- request body size limit and API response headers
- lazy default app (importing pynode.server must not build an app)
- entrypoint helpers: exposure warning, logging to a rotating file, SIGTERM
- MQTT client creation on paho's current callback API

Everything runs against the sandboxed ``api_app`` / ``api_client`` fixtures
(tmp dirs) or pure helper functions - nothing touches the real workflows dir.
"""

import logging
import signal
import subprocess
import sys

import pytest

from pynode import main as pynode_main
from pynode import server


# --- health --------------------------------------------------------------

def test_healthz_is_open_even_with_an_api_key(api_client):
    api_client.application.config['PYNODE_API_KEY'] = 'secret'

    resp = api_client.get('/healthz')

    assert resp.status_code == 200
    assert resp.get_json() == {'status': 'ok'}


def test_api_health_requires_the_api_key(api_client):
    api_client.application.config['PYNODE_API_KEY'] = 'secret'

    assert api_client.get('/api/health').status_code == 401
    assert api_client.get('/api/health', headers={'X-API-Key': 'secret'}).status_code == 200


def test_api_health_reports_workflows(api_client):
    api_client.application.config['PYNODE_API_KEY'] = ''
    wf_id = api_client.post('/api/workflows', json={'name': 'line 1'}).get_json()['id']

    body = api_client.get('/api/health').get_json()

    assert body['success'] is True and body['status'] == 'ok'
    assert isinstance(body['version'], str) and body['version']
    assert body['uptime_seconds'] >= 0
    # A newly created workflow is deployed and running straight away.
    assert body['workflow_count'] == 1 and body['running_count'] == 1
    entry = body['workflows'][0]
    # `nodes` counts the engine's built-in system error node too.
    assert isinstance(entry.pop('nodes'), int)
    assert entry == {'id': wf_id, 'name': 'line 1', 'enabled': True, 'running': True}

    assert api_client.post(f'/api/workflow/stop?workflow={wf_id}').status_code == 200
    body = api_client.get('/api/health').get_json()
    assert body['status'] == 'ok' and body['running_count'] == 0
    assert body['workflows'][0]['running'] is False


# --- request limits / headers -------------------------------------------

@pytest.mark.parametrize('value, expected', [
    (None, 4096), ('', 4096), ('512', 512), (64, 64), ('0', 0), ('-5', 4096), ('lots', 4096),
])
def test_parse_max_upload_mb(value, expected):
    assert server._parse_max_upload_mb(value) == expected


def test_oversized_body_gets_a_json_413(tmp_path):
    app = server.create_app({
        'WORKFLOWS_DIR': str(tmp_path / 'wf'),
        'WORKFLOW_FILE': str(tmp_path / 'wf' / 'workflow.json'),
        'UPLOAD_BASE_DIR': str(tmp_path / 'up'),
        'MQTT_SERVICES_FILE': str(tmp_path / 'wf' / 'services' / 'mqtt_services.json'),
        'PYNODE_API_KEY': '',
        'MAX_UPLOAD_MB': 1,
        'TESTING': True,
    })
    manager = app.extensions['workflow_manager']
    try:
        assert app.config['MAX_CONTENT_LENGTH'] == 1024 * 1024
        resp = app.test_client().post(
            '/api/workflows', data=b'x' * (2 * 1024 * 1024), content_type='application/json')
        assert resp.status_code == 413
        assert resp.get_json()['success'] is False
    finally:
        manager.shutdown()


def test_unlimited_upload_when_zero(tmp_path):
    app = server.create_app({
        'WORKFLOWS_DIR': str(tmp_path / 'wf'),
        'WORKFLOW_FILE': str(tmp_path / 'wf' / 'workflow.json'),
        'UPLOAD_BASE_DIR': str(tmp_path / 'up'),
        'MQTT_SERVICES_FILE': str(tmp_path / 'wf' / 'services' / 'mqtt_services.json'),
        'MAX_UPLOAD_MB': 0,
        'TESTING': True,
    })
    try:
        assert app.config.get('MAX_CONTENT_LENGTH') is None
    finally:
        app.extensions['workflow_manager'].shutdown()


def test_api_responses_are_nosniff_and_static_is_untouched(api_client):
    api_client.application.config['PYNODE_API_KEY'] = ''

    assert api_client.get('/api/node-types').headers['X-Content-Type-Options'] == 'nosniff'
    assert 'X-Content-Type-Options' not in api_client.get('/').headers


# --- lazy default app ----------------------------------------------------

def test_importing_the_server_module_builds_no_app():
    """Run in a fresh interpreter: this process may already have built one."""
    code = (
        "import pynode.server as s; "
        "assert s._default_app is None, 'default app was created at import'; "
        "assert callable(s.create_app); "
        "print('lazy')"
    )
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith('lazy')


def test_unknown_module_attribute_still_raises():
    with pytest.raises(AttributeError):
        server.no_such_attribute  # noqa: B018


def test_shutdown_default_app_is_a_noop_when_never_created(monkeypatch):
    monkeypatch.setattr(server, '_default_app', None)
    server.shutdown_default_app()   # must not create (or touch) an app
    assert server._default_app is None


# --- entrypoint helpers --------------------------------------------------

@pytest.mark.parametrize('host, key, warns', [
    ('0.0.0.0', '', True),
    ('192.168.1.20', None, True),
    ('0.0.0.0', 'secret', False),
    ('127.0.0.1', '', False),
    ('localhost', '', False),
    ('::1', '', False),
])
def test_exposure_warning(host, key, warns):
    warning = pynode_main.exposure_warning(host, key)
    assert (warning is not None) is warns
    if warns:
        assert 'API key' in warning and host in warning


def test_env_int(monkeypatch):
    monkeypatch.delenv('PYNODE_THREADS', raising=False)
    assert pynode_main._env_int('PYNODE_THREADS', 32) == 32
    monkeypatch.setenv('PYNODE_THREADS', '64')
    assert pynode_main._env_int('PYNODE_THREADS', 32) == 64
    for bad in ('0', '-4', 'many'):
        monkeypatch.setenv('PYNODE_THREADS', bad)
        assert pynode_main._env_int('PYNODE_THREADS', 32) == 32


def test_configure_logging_writes_a_rotating_file(tmp_path):
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    log_file = tmp_path / 'logs' / 'pynode.log'
    try:
        pynode_main.configure_logging('warning', str(log_file))
        logging.getLogger('pynode.test').warning('disk almost full')
        for handler in root.handlers:
            handler.flush()

        assert root.level == logging.WARNING
        rotating = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert len(rotating) == 1 and rotating[0].maxBytes > 0 and rotating[0].backupCount > 0
        assert 'disk almost full' in log_file.read_text(encoding='utf-8')
    finally:
        for handler in root.handlers[:]:
            if handler not in saved_handlers:
                handler.close()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_sigterm_becomes_keyboard_interrupt():
    saved = signal.getsignal(signal.SIGTERM)
    try:
        pynode_main.install_signal_handlers()
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)
    finally:
        signal.signal(signal.SIGTERM, saved)


def test_main_stops_workflows_on_interrupt(monkeypatch):
    """A terminated server must run node on_stop hooks before exiting."""
    calls = []

    class _App:
        config = {'PYNODE_API_KEY': 'k'}

    monkeypatch.setattr(sys, 'argv', ['pynode', '--host', '127.0.0.1'])
    monkeypatch.setattr(server, 'get_default_app', lambda: _App())
    monkeypatch.setattr(server, 'load_workflow_from_disk', lambda: calls.append('load'))
    monkeypatch.setattr(server, 'shutdown_default_app', lambda: calls.append('shutdown'))
    monkeypatch.setattr(pynode_main, 'configure_logging', lambda *a, **k: None)
    monkeypatch.setattr(pynode_main, 'install_signal_handlers', lambda: None)

    def _interrupted(app, args):
        calls.append('serve')
        raise KeyboardInterrupt

    monkeypatch.setattr(pynode_main, '_serve', _interrupted)

    pynode_main.main()

    assert calls == ['load', 'serve', 'shutdown']


# --- MQTT client API -----------------------------------------------------

def test_mqtt_client_uses_current_callback_api():
    pytest.importorskip('paho.mqtt.client')
    import warnings

    from pynode.nodes.MQTTNode import mqtt_service

    with warnings.catch_warnings():
        warnings.simplefilter('error', DeprecationWarning)
        client = mqtt_service._new_client('pynode_test_client', True)

    assert client is not None


def test_mqtt_result_codes_from_both_callback_apis():
    from pynode.nodes.MQTTNode import mqtt_service

    class _Reason:
        def __init__(self, failure):
            self.is_failure = failure

        def __str__(self):
            return 'Not authorized'

    assert mqtt_service._rc_ok(0) and not mqtt_service._rc_ok(5)
    assert mqtt_service._rc_ok(_Reason(False)) and not mqtt_service._rc_ok(_Reason(True))
    assert mqtt_service._rc_text(_Reason(True)) == 'Not authorized'
