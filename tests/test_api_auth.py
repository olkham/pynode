"""Tests for optional API key authentication and configurable CORS.

API key (server.py ``_require_api_key`` before_request hook):
- Unset/empty ``app.config['PYNODE_API_KEY']`` disables auth entirely
  (today's default behavior: no 401 anywhere).
- A non-empty key gates every /api/ route: accepted via the X-API-Key
  header OR the api_key query parameter (EventSource cannot set headers).
- Static assets and the index page stay open so the UI can load and
  prompt for the key.

CORS: ``CORS(app, origins=...)`` runs at pynode.server import time, so the
already-imported module's CORS behavior cannot be reconfigured per-test
without reimporting pynode.server - and reimporting would break other test
modules' identity (module-global engines/state). The tests below therefore
(a) unit-test the ``_parse_cors_origins`` helper, (b) exercise flask-cors
allowed/disallowed origin handling on a fresh throwaway Flask app wired the
same way server.py wires it, and (c) assert the imported app's default is
open CORS.
"""

import pytest
from flask import Flask
from flask_cors import CORS

import pynode.server as server


@pytest.fixture
def auth_client(api_client):
    """api_client with auth explicitly disabled; restores the key after."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(server.app.config, 'PYNODE_API_KEY', '')
        yield api_client


@pytest.fixture
def keyed_client(api_client):
    """api_client with an API key configured; restores the key after."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(server.app.config, 'PYNODE_API_KEY', 'test-secret-key')
        yield api_client


# ------------------------------------------------------------------
# No key configured -> behavior identical to today (no 401 anywhere)
# ------------------------------------------------------------------

class TestAuthDisabled:
    def test_api_route_open_without_key(self, auth_client):
        resp = auth_client.get('/api/node-types')
        assert resp.status_code == 200

    def test_index_open(self, auth_client):
        assert auth_client.get('/').status_code == 200

    def test_static_asset_open(self, auth_client):
        assert auth_client.get('/js/main.js').status_code == 200

    def test_write_route_open(self, auth_client):
        resp = auth_client.post('/api/workflows', json={'name': 'wf'})
        assert resp.status_code == 201

    def test_empty_string_key_disables_auth(self, auth_client):
        # Explicit empty string == unset == auth disabled
        assert server.app.config['PYNODE_API_KEY'] == ''
        resp = auth_client.get('/api/node-types')
        assert resp.status_code == 200


# ------------------------------------------------------------------
# Key configured -> /api/ routes require it; UI assets stay open
# ------------------------------------------------------------------

class TestAuthEnabled:
    def test_missing_key_gets_401_json_envelope(self, keyed_client):
        resp = keyed_client.get('/api/node-types')
        assert resp.status_code == 401
        body = resp.get_json()
        assert body == {'success': False,
                        'error': 'Invalid or missing API key'}

    def test_correct_header_key_gets_200(self, keyed_client):
        resp = keyed_client.get('/api/node-types',
                                headers={'X-API-Key': 'test-secret-key'})
        assert resp.status_code == 200

    def test_wrong_header_key_gets_401(self, keyed_client):
        resp = keyed_client.get('/api/node-types',
                                headers={'X-API-Key': 'wrong-key'})
        assert resp.status_code == 401
        assert resp.get_json()['success'] is False

    def test_correct_query_param_key_gets_200(self, keyed_client):
        # EventSource cannot set headers, so ?api_key= must work too
        resp = keyed_client.get('/api/node-types?api_key=test-secret-key')
        assert resp.status_code == 200

    def test_wrong_query_param_key_gets_401(self, keyed_client):
        resp = keyed_client.get('/api/node-types?api_key=nope')
        assert resp.status_code == 401

    def test_index_still_open_without_key(self, keyed_client):
        assert keyed_client.get('/').status_code == 200

    def test_static_asset_still_open_without_key(self, keyed_client):
        assert keyed_client.get('/js/main.js').status_code == 200

    def test_write_route_requires_key(self, keyed_client):
        resp = keyed_client.post('/api/workflows', json={'name': 'wf'})
        assert resp.status_code == 401
        resp = keyed_client.post('/api/workflows', json={'name': 'wf'},
                                 headers={'X-API-Key': 'test-secret-key'})
        assert resp.status_code == 201

    def test_options_preflight_not_blocked(self, keyed_client):
        # CORS preflight requests cannot carry custom headers; the hook
        # must let them through so flask-cors can answer them.
        resp = keyed_client.options(
            '/api/node-types',
            headers={'Origin': 'http://example.com',
                     'Access-Control-Request-Method': 'GET'})
        assert resp.status_code != 401


# ------------------------------------------------------------------
# CORS origin parsing helper
# ------------------------------------------------------------------

class TestParseCorsOrigins:
    def test_none_means_all(self):
        assert server._parse_cors_origins(None) == '*'

    def test_empty_string_means_all(self):
        assert server._parse_cors_origins('') == '*'

    def test_blank_string_means_all(self):
        assert server._parse_cors_origins('  , ,') == '*'

    def test_star_means_all(self):
        assert server._parse_cors_origins('*') == '*'
        assert server._parse_cors_origins('http://a.com,*') == '*'

    def test_single_origin(self):
        assert server._parse_cors_origins('http://a.com') == ['http://a.com']

    def test_multiple_origins_stripped(self):
        result = server._parse_cors_origins(' http://a.com , https://b.org ')
        assert result == ['http://a.com', 'https://b.org']


# ------------------------------------------------------------------
# CORS behavior. The imported pynode.server app was configured at import
# time (default: open), which is asserted directly. Restricted-origin
# behavior is exercised on a fresh Flask app wired exactly like server.py
# wires it, because reconfiguring flask-cors on the imported app would
# require reimporting pynode.server (breaking module identity for the
# rest of the suite).
# ------------------------------------------------------------------

class TestCorsBehavior:
    def test_default_app_allows_any_origin(self, auth_client):
        # flask-cors with origins='*' (and default send_wildcard=False)
        # echoes the request Origin - the same behavior as the previous
        # bare CORS(app): any origin is allowed.
        resp = auth_client.get('/api/node-types',
                               headers={'Origin': 'http://anywhere.example'})
        assert resp.status_code == 200
        assert (resp.headers.get('Access-Control-Allow-Origin')
                == 'http://anywhere.example')

    @pytest.fixture
    def restricted_app_client(self):
        fresh = Flask(__name__)
        CORS(fresh, origins=server._parse_cors_origins(
            'http://allowed.example, https://also-allowed.example'))

        @fresh.route('/api/ping')
        def ping():
            return {'success': True}

        fresh.config['TESTING'] = True
        with fresh.test_client() as c:
            yield c

    def test_allowed_origin_gets_cors_header(self, restricted_app_client):
        resp = restricted_app_client.get(
            '/api/ping', headers={'Origin': 'http://allowed.example'})
        assert resp.status_code == 200
        assert (resp.headers.get('Access-Control-Allow-Origin')
                == 'http://allowed.example')

    def test_second_allowed_origin_gets_cors_header(self, restricted_app_client):
        resp = restricted_app_client.get(
            '/api/ping', headers={'Origin': 'https://also-allowed.example'})
        assert (resp.headers.get('Access-Control-Allow-Origin')
                == 'https://also-allowed.example')

    def test_disallowed_origin_gets_no_cors_header(self, restricted_app_client):
        resp = restricted_app_client.get(
            '/api/ping', headers={'Origin': 'http://evil.example'})
        assert resp.status_code == 200  # CORS is a browser gate, not auth
        assert resp.headers.get('Access-Control-Allow-Origin') is None
