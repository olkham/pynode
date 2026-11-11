"""Credential store API.

Write-only by design: no response ever contains a secret value. Listings
return the public view (id, name, type, non-secret fields, the names of the
secret fields that are set) plus ``inUse``, the number of nodes and MQTT
brokers that reference the credential.

Status codes: 400 for invalid input, 404 for an unknown ID, 409 when
deleting a credential still in use, 500 when the store itself fails (no
key, wrong key, unreadable file).
"""

from flask import Blueprint, current_app, jsonify

from pynode.api.helpers import (
    _INVALID_BODY_ERROR, _get_json_body, _get_manager, _get_mqtt_manager, _json_error)
from pynode.credential_store import CredentialError, list_credential_types

credentials_bp = Blueprint('credentials', __name__)


def _store():
    """The CredentialStore of the app handling the current request."""
    return current_app.extensions['credential_store']


def _usage(credential_ids):
    """{credential_id: count} of the nodes and MQTT brokers referencing each ID."""
    usage = dict(_get_manager().credential_usage(credential_ids))
    for cred_id, count in _get_mqtt_manager().credential_usage(credential_ids).items():
        usage[cred_id] = usage.get(cred_id, 0) + count
    return usage


def _with_usage(credential, usage):
    credential['inUse'] = usage.get(credential['id'], 0)
    return credential


@credentials_bp.route('/api/credential-types', methods=['GET'])
def get_credential_types():
    """List the registered credential types and their fields."""
    return jsonify({'success': True, 'types': list_credential_types()})


@credentials_bp.route('/api/credentials', methods=['GET'])
def list_credentials():
    """List credentials (public view only)."""
    try:
        credentials = _store().list()
        usage = _usage([c['id'] for c in credentials])
        credentials = [_with_usage(c, usage) for c in credentials]
    except CredentialError as e:
        return _json_error(str(e), 500)
    return jsonify({'success': True, 'credentials': credentials})


@credentials_bp.route('/api/credentials', methods=['POST'])
def create_credential():
    """Create a credential from {'name', 'type', 'fields'}."""
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    try:
        credential = _store().create(data.get('name'), data.get('type'), data.get('fields') or {})
    except ValueError as e:
        return _json_error(str(e), 400)
    except CredentialError as e:
        return _json_error(str(e), 500)
    return jsonify({'success': True, 'credential': _with_usage(credential, {})})


@credentials_bp.route('/api/credentials/<cred_id>', methods=['PUT'])
def update_credential(cred_id):
    """Rename and/or change fields; a secret field left out (or empty) is kept."""
    data = _get_json_body()
    if data is None:
        return _json_error(_INVALID_BODY_ERROR, 400)
    try:
        credential = _store().update(cred_id, name=data.get('name'), fields=data.get('fields'))
    except ValueError as e:
        return _json_error(str(e), 400)
    except CredentialError as e:
        return _json_error(str(e), 500)
    if credential is None:
        return _json_error('Credential not found', 404)
    return jsonify({'success': True,
                    'credential': _with_usage(credential, _usage([cred_id]))})


@credentials_bp.route('/api/credentials/<cred_id>', methods=['DELETE'])
def delete_credential(cred_id):
    """Delete a credential unless a node in any workflow, or an MQTT broker, still references it."""
    store = _store()
    try:
        if store.get(cred_id) is None:
            return _json_error('Credential not found', 404)
        in_use = _usage([cred_id]).get(cred_id, 0)
        if in_use:
            return _json_error(f'Credential is used by {in_use} node(s) or broker(s)', 409)
        store.delete(cred_id)
    except CredentialError as e:
        return _json_error(str(e), 500)
    return jsonify({'success': True})
