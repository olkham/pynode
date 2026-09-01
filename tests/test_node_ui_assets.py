"""Tests for node-supplied editor assets (``BaseNode.ui_assets``).

Covers the declaration side (what ``_resolve_ui_assets`` accepts and rejects),
the payload side (``/api/node-types`` carries the URLs), and the route side
(exact-match serving, and - the important one - that the route stays reachable
when an API key is configured).
"""

import pytest

from pynode import node_registry
from pynode.nodes.base_node import BaseNode


# ------------------------------------------------------------------
# What the shipped nodes declare
# ------------------------------------------------------------------

class TestDeclaredAssets:

    def test_every_registered_asset_exists_and_is_inside_its_node_folder(self):
        """Nothing servable may point outside the node folder that declared it."""
        import os

        nodes_root = os.path.realpath(str(node_registry._NODES_ROOT))
        assert node_registry.ui_asset_registry, 'no node declares ui_assets'

        for url_path, file_path in node_registry.ui_asset_registry.items():
            real = os.path.realpath(file_path)
            assert os.path.isfile(real), f'{url_path} -> missing file {real}'
            assert real.startswith(nodes_root + os.sep), f'{url_path} escapes the nodes dir'
            assert os.path.splitext(real)[1].lower() in node_registry.UI_ASSET_SUFFIXES

            # The URL names the declaring node folder, then the path within it.
            assert url_path.startswith(f'{node_registry.UI_ASSET_URL_PREFIX}/')
            folder = url_path[len(node_registry.UI_ASSET_URL_PREFIX) + 1:].split('/')[0]
            assert os.path.realpath(os.path.join(nodes_root, folder)) == os.path.dirname(
                os.path.dirname(real)) or folder in real

    def test_node_types_payload_exposes_ui_assets(self, api_client):
        resp = api_client.get('/api/node-types')
        assert resp.status_code == 200
        by_type = {t['type']: t for t in resp.get_json()}

        # ChangeNode's rules editor is the largest of the migrated ones.
        assets = by_type['ChangeNode']['uiAssets']
        assert assets['js'], 'ChangeNode declares no JS asset'
        assert assets['js'][0].startswith('/node-ui/ChangeNode/ui/change-rules.js')

    def test_every_node_type_carries_a_ui_assets_field(self, api_client):
        """Absent declarations serialize as {}, never as a missing key."""
        for node_type in api_client.get('/api/node-types').get_json():
            assert isinstance(node_type['uiAssets'], dict)

    def test_declaring_node_ships_an_editor_for_its_custom_property_types(self):
        """Guards the drift this whole mechanism exists to make visible.

        A node declaring a property type the core panel does not implement must
        ship a UI module that registers an editor for it, or the panel will
        render the "no editor registered" row at runtime.
        """
        import os

        # Property types the core properties.js renders itself.
        builtin = {
            'text', 'password', 'number', 'checkbox', 'textarea', 'select',
            'button', 'toggle', 'file', 'multiselect', 'hint',
        }

        registered_sources = {}
        for url_path, file_path in node_registry.ui_asset_registry.items():
            if file_path.lower().endswith('.js'):
                with open(file_path, encoding='utf-8') as handle:
                    registered_sources[url_path] = handle.read()

        missing = []
        for node_type in node_registry.get_node_types():
            custom = {p.get('type') for p in node_type['properties']
                      if isinstance(p, dict) and p.get('type') not in builtin}
            custom.discard(None)
            if not custom:
                continue

            declared_js = node_type.get('uiAssets', {}).get('js', [])
            sources = ''.join(
                registered_sources.get(url.split('?')[0], '') for url in declared_js)
            for prop_type in custom:
                # Either quote style, so an author's choice cannot fail this.
                if not any(f'propertyType: {q}{prop_type}{q}' in sources
                           for q in ("'", '"')):
                    missing.append((node_type['type'], prop_type))

        assert not missing, f'property types with no editor shipped by their node: {missing}'


# ------------------------------------------------------------------
# Declaration validation
# ------------------------------------------------------------------

class TestResolveValidation:
    """``_resolve_ui_assets`` drops bad entries rather than raising."""

    def _resolve(self, declared):
        # SwitchNode is a real node in a real folder, so only `ui_assets` varies.
        from pynode.nodes.SwitchNode.switch_node import SwitchNode

        class _Probe(SwitchNode):
            ui_assets = declared

        # The subclass is defined here, so point resolution at the real module.
        _Probe.__module__ = SwitchNode.__module__
        return node_registry._resolve_ui_assets(_Probe, '_Probe')

    def test_valid_declaration_resolves(self):
        assert self._resolve({'js': ['ui/rules.js']})['js']

    def test_traversal_is_rejected(self):
        assert self._resolve({'js': ['../InjectNode/ui/inject-props.js']}) == {}

    def test_deep_traversal_is_rejected(self):
        assert self._resolve({'js': ['../../../pynode/server.py']}) == {}

    def test_missing_file_is_rejected(self):
        assert self._resolve({'js': ['ui/not-here.js']}) == {}

    def test_disallowed_suffix_is_rejected(self):
        assert self._resolve({'js': ['switch_node.py']}) == {}

    def test_empty_declaration_resolves_to_nothing(self):
        assert self._resolve({}) == {}

    def test_base_node_declares_nothing(self):
        assert BaseNode.ui_assets == {}


# ------------------------------------------------------------------
# The route
# ------------------------------------------------------------------

@pytest.fixture
def asset_url():
    """A declared asset URL, without its cache-busting query."""
    return '/node-ui/ChangeNode/ui/change-rules.js'


class TestAssetRoute:

    def test_declared_asset_is_served(self, api_client, asset_url):
        resp = api_client.get(asset_url)
        assert resp.status_code == 200
        assert resp.mimetype == 'text/javascript'
        assert b"propertyType: 'changeRules'" in resp.data

    def test_cache_busting_query_is_accepted(self, api_client, asset_url):
        assert api_client.get(f'{asset_url}?v=123').status_code == 200

    def test_response_is_cacheable(self, api_client, asset_url):
        # Safe because the URL the client is given carries the file's mtime.
        assert 'immutable' in api_client.get(asset_url).headers['Cache-Control']

    def test_undeclared_file_in_a_node_folder_is_not_served(self, api_client):
        assert api_client.get('/node-ui/ChangeNode/change_node.py').status_code == 404

    def test_undeclared_asset_path_is_not_served(self, api_client):
        assert api_client.get('/node-ui/ChangeNode/ui/nope.js').status_code == 404

    def test_unknown_node_folder_is_not_served(self, api_client):
        assert api_client.get('/node-ui/NoSuchNode/ui/x.js').status_code == 404

    @pytest.mark.parametrize('path', [
        '/node-ui/../server.py',
        '/node-ui/ChangeNode/../../server.py',
        '/node-ui/ChangeNode/ui/../../change_node.py',
        '/node-ui/%2e%2e/server.py',
    ])
    def test_traversal_attempts_are_refused(self, api_client, path):
        # Werkzeug may normalize some of these into a redirect; what matters is
        # that no request ever comes back with file contents.
        resp = api_client.get(path)
        assert resp.status_code != 200
        assert b'workflow_manager' not in resp.data


class TestAssetRouteWithApiKey:
    """The regression guard for the constraint that shaped the URL prefix.

    Node UI assets are fetched by dynamic import() and <link>, neither of which
    goes through the auth.js fetch wrapper that attaches X-API-Key. If this
    route ever moves under /api/, the editor 401s for every keyed deployment -
    so assert it stays reachable with a key configured.
    """

    def test_asset_is_reachable_without_the_key(self, api_client, asset_url):
        api_client.application.config['PYNODE_API_KEY'] = 'test-secret-key'
        assert api_client.get(asset_url).status_code == 200

    def test_api_route_still_requires_the_key(self, api_client):
        api_client.application.config['PYNODE_API_KEY'] = 'test-secret-key'
        assert api_client.get('/api/node-types').status_code == 401
