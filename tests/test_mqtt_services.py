"""Tests for MQTT broker (service) management API and the test-connection helper.

Safety: every test runs against the sandboxed ``create_app()`` fixture, whose
MQTT manager writes to a tmp services file - never the real
``workflows/services/mqtt_services.json``. The test-connection success path
mocks the paho client so no live broker is required; the failure path uses a
closed local port with a short timeout.
"""

import json

import pytest


def _create(api_client, **overrides):
    body = {'name': 'Broker A', 'broker': 'localhost', 'port': 1883}
    body.update(overrides)
    return api_client.post('/api/services/mqtt', json=body)


def test_mqtt_manager_is_isolated_to_tmp(api_app, tmp_path):
    """The sandboxed app must not share the real global manager or its file."""
    from pynode.nodes.MQTTNode.mqtt_service import mqtt_manager as global_manager

    app_manager = api_app.extensions['mqtt_manager']
    assert app_manager is not global_manager
    assert str(tmp_path) in str(app_manager.config_file)


def test_service_crud_roundtrip(api_client, api_app):
    # create
    resp = _create(api_client, name='Home', broker='192.168.1.10', port=1884)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    sid = data['service']['id']
    assert data['service']['broker'] == '192.168.1.10'

    # list
    resp = api_client.get('/api/services/mqtt')
    services = resp.get_json()['services']
    assert any(s['id'] == sid for s in services)

    # get full config
    resp = api_client.get(f'/api/services/mqtt/{sid}')
    svc = resp.get_json()['service']
    assert svc['name'] == 'Home'
    assert svc['port'] == 1884

    # update (round-trips every field)
    resp = api_client.put(f'/api/services/mqtt/{sid}', json={
        'name': 'Home2', 'broker': 'mqtt.local', 'port': 8883,
        'username': 'u', 'password': 'p', 'keepAlive': 30, 'cleanSession': False,
    })
    assert resp.status_code == 200
    svc = resp.get_json()['service']
    assert svc['name'] == 'Home2'
    assert svc['broker'] == 'mqtt.local'
    assert svc['port'] == 8883
    assert svc['keepAlive'] == 30
    assert svc['cleanSession'] is False

    # persisted to the tmp file in the backward-compatible format
    cfg = api_app.extensions['mqtt_manager'].config_file
    saved = json.loads(cfg.read_text())
    assert 'services' in saved
    assert any(s['id'] == sid and s['name'] == 'Home2' for s in saved['services'])

    # delete
    resp = api_client.delete(f'/api/services/mqtt/{sid}')
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True

    # gone
    resp = api_client.get(f'/api/services/mqtt/{sid}')
    assert resp.status_code == 404


def test_create_requires_name_and_broker(api_client):
    assert api_client.post('/api/services/mqtt', json={'broker': 'x'}).status_code == 400
    assert api_client.post('/api/services/mqtt', json={'name': 'x'}).status_code == 400


def test_update_missing_service_404(api_client):
    r = api_client.put('/api/services/mqtt/nope', json={'name': 'a', 'broker': 'b'})
    assert r.status_code == 404


def test_delete_missing_service_400(api_client):
    r = api_client.delete('/api/services/mqtt/nope')
    assert r.status_code == 400
    assert r.get_json()['success'] is False


def test_test_endpoint_failure_closed_port(api_client):
    """A closed local port fails fast and deterministically."""
    r = api_client.post('/api/services/mqtt/test',
                        json={'broker': '127.0.0.1', 'port': 1})
    assert r.status_code == 200
    data = r.get_json()
    assert data['success'] is False
    assert data['error']


def test_test_endpoint_requires_broker(api_client):
    r = api_client.post('/api/services/mqtt/test', json={'port': 1883})
    assert r.status_code == 400


def _make_fake_client(rc):
    class _FakeClient:
        def __init__(self, *a, **k):
            self.on_connect = None

        def username_pw_set(self, *a, **k):
            pass

        def connect(self, host, port, keepalive=60):
            pass

        def loop_start(self):
            # Simulate the broker's CONNACK arriving on the network loop.
            if self.on_connect:
                self.on_connect(self, None, None, rc)

        def loop_stop(self):
            pass

        def disconnect(self):
            pass

    return _FakeClient


def test_test_connection_success_mocked(monkeypatch):
    from pynode.nodes.MQTTNode import mqtt_service

    if not getattr(mqtt_service, 'MQTT_AVAILABLE', False):
        pytest.skip('paho-mqtt not installed')

    monkeypatch.setattr(mqtt_service, 'MQTT_AVAILABLE', True)
    monkeypatch.setattr(mqtt_service.mqtt, 'Client', _make_fake_client(0))
    ok, err = mqtt_service.test_connection({'broker': 'x', 'port': 1883}, timeout=2.0)
    assert ok is True
    assert err is None


def test_test_connection_refused_mocked(monkeypatch):
    from pynode.nodes.MQTTNode import mqtt_service

    if not getattr(mqtt_service, 'MQTT_AVAILABLE', False):
        pytest.skip('paho-mqtt not installed')

    monkeypatch.setattr(mqtt_service, 'MQTT_AVAILABLE', True)
    monkeypatch.setattr(mqtt_service.mqtt, 'Client', _make_fake_client(5))  # not authorized
    ok, err = mqtt_service.test_connection({'broker': 'x', 'port': 1883}, timeout=2.0)
    assert ok is False
    assert err
