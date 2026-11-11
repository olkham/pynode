"""An MQTT broker takes its password from a stored credential.

Safety: everything runs against the sandboxed ``create_app()`` fixture, so
the services file, the credential store and its key all live under tmp_path.
No broker is contacted: the paho client is replaced by a fake that records
what it was given. The fake's only thread is joined when its loop is stopped.
"""

import json
import threading

import pytest

SECRET = 'pw-SHOULD-NEVER-LEAK-123'


@pytest.fixture
def paho(monkeypatch):
    """Fake paho client class; yields the list of calls made on its instances."""
    from pynode.nodes.MQTTNode import mqtt_service

    if not getattr(mqtt_service, 'MQTT_AVAILABLE', False):
        pytest.skip('paho-mqtt not installed')
    calls = []

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.on_connect = None
            self._loop = threading.Thread(target=lambda: None)
            self._loop.start()

        def username_pw_set(self, username, password=None):
            calls.append(('auth', username, password))

        def connect(self, host, port, *args, **kwargs):
            calls.append(('connect', host, port))

        def loop_start(self):
            # The broker's CONNACK arrives on paho's network thread, never
            # on the caller's: MQTTService.connect() holds its lock here and
            # its on_connect callback takes the same lock.
            self._loop = threading.Thread(
                target=lambda: self.on_connect and self.on_connect(self, None, None, 0),
                daemon=True)
            self._loop.start()

        def loop_stop(self):
            # Every code path under test stops the loop it started, so the
            # thread is always joined before the test ends.
            self._loop.join(timeout=5)
            assert not self._loop.is_alive()

        def disconnect(self):
            pass

        def subscribe(self, *args, **kwargs):
            pass

    monkeypatch.setattr(mqtt_service.mqtt, 'Client', _FakeClient)
    return calls


def _manager(api_app):
    return api_app.extensions['mqtt_manager']


def _credential(client, value=SECRET):
    resp = client.post('/api/credentials',
                       json={'name': 'broker password', 'type': 'secret', 'fields': {'value': value}})
    assert resp.status_code == 200
    return resp.get_json()['credential']['id']


def _create(client, **overrides):
    body = {'name': 'Broker', 'broker': 'mqtt.local', 'port': 1883, 'username': 'user'}
    body.update(overrides)
    resp = client.post('/api/services/mqtt', json=body)
    assert resp.status_code == 200
    return resp.get_json()['service']


def _on_disk(api_app, service_id):
    saved = json.loads(_manager(api_app).config_file.read_text())
    return next(s for s in saved['services'] if s['id'] == service_id)


def test_manager_shares_the_apps_credential_store(api_app):
    assert _manager(api_app).credential_store is api_app.extensions['credential_store']


def test_broker_stores_only_the_credential_id(api_client, api_app):
    cred_id = _credential(api_client)
    service = _create(api_client, credential=cred_id)
    assert service['credential'] == cred_id
    assert service['hasPassword'] is False
    assert _on_disk(api_app, service['id'])['credential'] == cred_id
    assert SECRET not in _manager(api_app).config_file.read_text()
    assert SECRET not in api_client.get('/api/services/mqtt').get_data(as_text=True)
    assert SECRET not in api_client.get(f"/api/services/mqtt/{service['id']}").get_data(as_text=True)


def test_connect_uses_the_credentials_password(api_client, api_app, paho):
    service = _create(api_client, credential=_credential(api_client))
    live = _manager(api_app).get_service(service['id'])
    try:
        assert live.connect() is True
    finally:
        live.disconnect()
    assert paho == [('auth', 'user', SECRET), ('connect', 'mqtt.local', 1883)]


def test_replaced_secret_is_used_on_the_next_connect(api_client, api_app, paho):
    cred_id = _credential(api_client)
    service = _create(api_client, credential=cred_id)
    assert api_client.put(f'/api/credentials/{cred_id}',
                          json={'fields': {'value': 'rotated'}}).status_code == 200
    live = _manager(api_app).get_service(service['id'])
    try:
        assert live.connect() is True
    finally:
        live.disconnect()
    assert paho[0] == ('auth', 'user', 'rotated')


def test_missing_credential_never_connects(api_client, api_app, paho):
    # Not even with the legacy password that was submitted alongside it.
    service = _create(api_client, credential='gone', password='legacy')
    live = _manager(api_app).get_service(service['id'])
    errors = []
    live.register_node('n1', errors.append)
    try:
        assert live.connect() is False
    finally:
        live.unregister_node('n1')
        live.disconnect()
    assert paho == []
    assert len(errors) == 1
    assert 'not found' in errors[0]


def test_legacy_password_still_connects_but_is_never_returned(api_client, api_app, paho):
    service = _create(api_client, password='legacy-pw')
    assert 'password' not in service
    assert service['hasPassword'] is True
    fetched = api_client.get(f"/api/services/mqtt/{service['id']}")
    assert 'legacy-pw' not in fetched.get_data(as_text=True)
    assert fetched.get_json()['service']['hasPassword'] is True
    assert _on_disk(api_app, service['id'])['password'] == 'legacy-pw'
    live = _manager(api_app).get_service(service['id'])
    try:
        assert live.connect() is True
    finally:
        live.disconnect()
    assert paho[0] == ('auth', 'user', 'legacy-pw')


def test_update_without_a_password_key_keeps_the_legacy_password(api_client, api_app):
    # The editor never holds the password, so it cannot send it back.
    service = _create(api_client, password='legacy-pw')
    resp = api_client.put(f"/api/services/mqtt/{service['id']}", json={
        'name': 'Renamed', 'broker': 'mqtt.local', 'port': 1883, 'username': 'user'})
    assert resp.get_json()['service']['hasPassword'] is True
    assert _on_disk(api_app, service['id'])['password'] == 'legacy-pw'


def test_update_can_remove_the_legacy_password(api_client, api_app):
    service = _create(api_client, password='legacy-pw')
    resp = api_client.put(f"/api/services/mqtt/{service['id']}", json={
        'name': 'Broker', 'broker': 'mqtt.local', 'username': 'user', 'password': ''})
    assert resp.get_json()['service']['hasPassword'] is False
    assert 'password' not in _on_disk(api_app, service['id'])


def test_selecting_a_credential_drops_the_legacy_password(api_client, api_app):
    service = _create(api_client, password='legacy-pw')
    cred_id = _credential(api_client)
    resp = api_client.put(f"/api/services/mqtt/{service['id']}", json={
        'name': 'Broker', 'broker': 'mqtt.local', 'username': 'user', 'credential': cred_id})
    updated = resp.get_json()['service']
    assert updated['credential'] == cred_id
    assert updated['hasPassword'] is False
    on_disk = _on_disk(api_app, service['id'])
    assert on_disk['credential'] == cred_id
    assert 'password' not in on_disk


def test_credential_used_by_a_broker_cannot_be_deleted(api_client):
    cred_id = _credential(api_client)
    service = _create(api_client, credential=cred_id)
    listed = api_client.get('/api/credentials').get_json()['credentials']
    assert next(c for c in listed if c['id'] == cred_id)['inUse'] == 1
    assert api_client.delete(f'/api/credentials/{cred_id}').status_code == 409
    # Once the broker is gone the credential can go too.
    assert api_client.delete(f"/api/services/mqtt/{service['id']}").status_code == 200
    assert api_client.delete(f'/api/credentials/{cred_id}').status_code == 200


def test_test_endpoint_resolves_the_credential_server_side(api_client, paho):
    cred_id = _credential(api_client)
    resp = api_client.post('/api/services/mqtt/test', json={
        'broker': 'mqtt.local', 'port': 1883, 'username': 'user', 'credential': cred_id})
    assert resp.get_json() == {'success': True, 'error': None}
    assert paho[0] == ('auth', 'user', SECRET)


def test_test_endpoint_uses_a_saved_brokers_legacy_password(api_client, paho):
    service = _create(api_client, password='legacy-pw')
    resp = api_client.post('/api/services/mqtt/test', json={
        'id': service['id'], 'broker': 'mqtt.local', 'port': 1883, 'username': 'user'})
    assert resp.get_json()['success'] is True
    assert paho[0] == ('auth', 'user', 'legacy-pw')


def test_test_endpoint_reports_a_missing_credential(api_client, paho):
    resp = api_client.post('/api/services/mqtt/test', json={
        'broker': 'mqtt.local', 'username': 'user', 'credential': 'gone'})
    data = resp.get_json()
    assert data['success'] is False
    assert 'not found' in data['error']
    assert paho == []


def test_manager_without_a_store_fails_loudly(tmp_path, paho):
    from pynode.nodes.MQTTNode.mqtt_service import MQTTServiceManager

    manager = MQTTServiceManager(config_file=tmp_path / 'services' / 'mqtt_services.json')
    service = manager.create_service({'name': 'B', 'broker': 'x', 'username': 'u',
                                      'credential': 'f' * 32})
    errors = []
    service.register_node('n1', errors.append)
    try:
        assert service.connect() is False
    finally:
        service.unregister_node('n1')
        service.disconnect()
    assert paho == []
    assert 'no credential store' in errors[0]
