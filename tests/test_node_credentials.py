"""Nodes other than WebhookNode take their secrets from the credential store.

Covers BaseNode.get_secret() and the nodes built on it: RESTEndpointNode
(inbound auth), RoboflowUploadNode (API key) and Qwen3VLMNode (HuggingFace
token). Nothing here opens a socket or starts a thread: the REST endpoint's
auth check is called directly, and the Roboflow / transformers packages are
replaced by in-memory fakes. Every store lives under tmp_path.
"""

import base64
import sys
import types

import pytest

from pynode.credential_store import CREDENTIAL_TYPES, CredentialStore
from pynode.nodes.base_node import BaseNode, CredentialError
from pynode.nodes.RESTEndpointNode.rest_endpoint_node import RESTEndpointNode
from pynode.nodes.RoboflowUploadNode.roboflow_upload_node import RoboflowUploadNode
from pynode.workflow_engine import WorkflowEngine

SECRET = 'tok-SHOULD-NEVER-LEAK-123'


class _SecretNode(BaseNode):
    properties = [{'name': 'credential', 'label': 'Credential', 'type': 'credential',
                   'credentialType': 'secret'}]


@pytest.fixture
def store(tmp_path):
    return CredentialStore(str(tmp_path / 'credentials.json'), environ={})


@pytest.fixture
def engine(store):
    eng = WorkflowEngine()
    eng.credential_store = store
    for node_class in (_SecretNode, RESTEndpointNode, RoboflowUploadNode):
        eng.register_node_type(node_class)
    return eng


def _secret(store, value=SECRET):
    return store.create('a secret', 'secret', {'value': value})['id']


def _errors(node):
    errors = []
    node.report_error = errors.append
    return errors


# -- BaseNode.get_secret ------------------------------------------------------

def test_get_secret_prefers_the_credential(engine, store):
    node = engine.create_node('_SecretNode', config={
        'credential': _secret(store), 'legacy': 'old-plain-text'})
    assert node.get_secret('credential', 'legacy') == SECRET


def test_get_secret_falls_back_to_the_legacy_field(engine):
    node = engine.create_node('_SecretNode', config={'credential': '', 'legacy': 'old-plain-text'})
    assert node.get_secret('credential', 'legacy') == 'old-plain-text'
    assert node.get_secret('credential') == ''


def test_get_secret_never_falls_back_when_the_credential_is_missing(engine):
    node = engine.create_node('_SecretNode', config={
        'credential': 'gone', 'legacy': 'old-plain-text'})
    with pytest.raises(CredentialError, match='not found'):
        node.get_secret('credential', 'legacy')


def test_get_secret_rejects_a_credential_of_another_type(engine, store, monkeypatch):
    monkeypatch.setitem(CREDENTIAL_TYPES, 'pair-test', {
        'type': 'pair-test', 'label': 'Pair',
        'fields': [{'name': 'user', 'label': 'User', 'secret': False},
                   {'name': 'pw', 'label': 'Password', 'secret': True}]})
    cred = store.create('pair', 'pair-test', {'user': 'u', 'pw': SECRET})
    node = engine.create_node('_SecretNode', config={'credential': cred['id']})
    with pytest.raises(CredentialError, match="has no 'value' field") as excinfo:
        node.get_secret('credential')
    assert SECRET not in str(excinfo.value)


# -- RESTEndpointNode ---------------------------------------------------------

def _rest_node(engine, **config):
    node = engine.create_node('RESTEndpointNode', config=config)
    return node, _errors(node)


def _basic(text):
    return 'Basic ' + base64.b64encode(text.encode()).decode()


def test_rest_endpoint_without_auth_accepts_everything(engine):
    node, _ = _rest_node(engine, authType='none')
    assert node._authorized({}) is True


def test_rest_endpoint_checks_bearer_against_the_credential(engine, store):
    node, errors = _rest_node(engine, authType='bearer', credential=_secret(store),
                              authCredentials='legacy-token')
    assert node._authorized({'Authorization': f'Bearer {SECRET}'}) is True
    # The credential takes precedence: the legacy value no longer opens the door.
    assert node._authorized({'Authorization': 'Bearer legacy-token'}) is False
    assert node._authorized({'Authorization': f'Bearer {SECRET}x'}) is False
    assert node._authorized({'Authorization': SECRET}) is False
    assert node._authorized({}) is False
    assert errors == []


def test_rest_endpoint_checks_basic_and_apikey_against_the_credential(engine, store):
    cred_id = _secret(store, value='user:päss word')
    basic, _ = _rest_node(engine, authType='basic', credential=cred_id)
    assert basic._authorized({'Authorization': _basic('user:päss word')}) is True
    assert basic._authorized({'Authorization': _basic('user:wrong')}) is False
    assert basic._authorized({'Authorization': 'Basic !!not-base64!!'}) is False
    apikey, _ = _rest_node(engine, authType='apikey', credential=cred_id)
    assert apikey._authorized({'X-API-Key': 'user:päss word'}) is True
    assert apikey._authorized({'X-API-Key': 'nope'}) is False
    assert apikey._authorized({}) is False


def test_rest_endpoint_legacy_auth_credentials_still_work(engine):
    node, _ = _rest_node(engine, authType='bearer', authCredentials='legacy-token')
    assert node._authorized({'Authorization': 'Bearer legacy-token'}) is True
    assert node._authorized({'Authorization': 'Bearer other'}) is False


def test_rest_endpoint_missing_credential_rejects_every_request(engine):
    node, errors = _rest_node(engine, authType='bearer', credential='gone',
                              authCredentials='legacy-token')
    assert node._authorized({'Authorization': 'Bearer legacy-token'}) is False
    assert node._authorized({'Authorization': 'Bearer gone'}) is False
    # Reported once, not once per rejected request.
    assert len(errors) == 1
    assert 'not found' in errors[0]


@pytest.mark.parametrize('auth_type', ['basic', 'bearer', 'apikey'])
def test_rest_endpoint_auth_without_a_secret_fails_closed(engine, auth_type):
    # Authentication switched on but nothing to compare against: an empty
    # or absent header must not match the empty secret.
    node, _ = _rest_node(engine, authType=auth_type)
    for headers in ({}, {'X-API-Key': ''}, {'Authorization': 'Bearer '},
                    {'Authorization': _basic('')}):
        assert node._authorized(headers) is False


def test_rest_endpoint_unknown_auth_type_is_rejected(engine):
    node, _ = _rest_node(engine, authType='digest', authCredentials='x')
    assert node._authorized({'Authorization': 'Bearer x'}) is False


# -- RoboflowUploadNode -------------------------------------------------------

@pytest.fixture
def fake_roboflow(monkeypatch):
    """Replace the roboflow package; yields the list of API keys it was given."""
    seen = []

    class _Workspace:
        def project(self, project_id):
            if project_id == 'broken':
                # The real SDK quotes the request URL, API key included.
                raise RuntimeError(f'404 for https://api.roboflow.com/ws/broken?api_key={seen[-1]}')
            return object()

    class Roboflow:
        def __init__(self, api_key):
            seen.append(api_key)

        def workspace(self, workspace_id):
            return _Workspace()

    module = types.ModuleType('roboflow')
    module.Roboflow = Roboflow
    monkeypatch.setitem(sys.modules, 'roboflow', module)
    return seen


def _roboflow_node(engine, **config):
    base = {'workspace_id': 'ws', 'project_id': 'proj'}
    base.update(config)
    node = engine.create_node('RoboflowUploadNode', config=base)
    return node, _errors(node)


def test_roboflow_api_key_comes_from_the_credential(engine, store, fake_roboflow):
    node, errors = _roboflow_node(engine, credential=_secret(store), api_key='legacy-key')
    node._connect()
    assert fake_roboflow == [SECRET]
    assert node._rf_project is not None
    assert errors == []


def test_roboflow_legacy_api_key_still_works(engine, fake_roboflow):
    node, _ = _roboflow_node(engine, api_key=' legacy-key ')
    node._connect()
    assert fake_roboflow == ['legacy-key']
    assert node._rf_project is not None


def test_roboflow_missing_credential_does_not_connect(engine, fake_roboflow):
    node, errors = _roboflow_node(engine, credential='gone', api_key='legacy-key')
    node._connect()
    assert fake_roboflow == []
    assert node._rf_project is None
    assert len(errors) == 1 and 'not found' in errors[0]


def test_roboflow_errors_never_quote_the_api_key(engine, store, fake_roboflow):
    node, errors = _roboflow_node(engine, credential=_secret(store), project_id='broken')
    node._connect()
    assert node._rf_project is None
    assert len(errors) == 1
    assert 'api_key=***' in errors[0]
    assert SECRET not in errors[0]


# -- Qwen3VLMNode -------------------------------------------------------------

@pytest.fixture
def qwen(engine, monkeypatch):
    """Qwen3VLMNode with transformers faked; yields (make_node, tokens seen)."""
    pytest.importorskip('numpy')
    from pynode.nodes.Qwen3VLMNode.qwen3_vlm_node import Qwen3VLMNode

    tokens = []

    class _Loader:
        @classmethod
        def from_pretrained(cls, model_name, token=None, **kwargs):
            tokens.append(token)
            return object()

    module = types.ModuleType('transformers')
    module.AutoModelForImageTextToText = _Loader
    module.AutoProcessor = _Loader
    monkeypatch.setitem(sys.modules, 'transformers', module)
    engine.register_node_type(Qwen3VLMNode)

    def make(**config):
        config.setdefault('device', 'cpu')
        node = engine.create_node('Qwen3VLMNode', config=config)
        return node, _errors(node)

    return make, tokens


def test_qwen_token_comes_from_the_credential(qwen, store):
    make, tokens = qwen
    node, errors = make(credential=_secret(store), hf_token='hf_legacy')
    assert node._load_model() is True
    assert tokens == [SECRET, SECRET]
    assert errors == []


def test_qwen_legacy_token_and_no_token_still_work(qwen):
    make, tokens = qwen
    legacy, _ = make(hf_token='hf_legacy')
    assert legacy._load_model() is True
    anonymous, _ = make()
    assert anonymous._load_model() is True
    assert tokens == ['hf_legacy', 'hf_legacy', None, None]


def test_qwen_missing_credential_does_not_load(qwen):
    make, tokens = qwen
    node, errors = make(credential='gone', hf_token='hf_legacy')
    assert node._load_model() is False
    assert tokens == []
    assert len(errors) == 1 and 'not found' in errors[0]


# -- no secret in the workflow ------------------------------------------------

def test_secrets_stay_out_of_the_exported_workflow(engine, store):
    cred_id = _secret(store)
    engine.create_node('RESTEndpointNode', config={'authType': 'bearer', 'credential': cred_id})
    engine.create_node('RoboflowUploadNode', config={'credential': cred_id})
    exported = repr(engine.export_workflow())
    assert cred_id in exported
    assert SECRET not in exported
