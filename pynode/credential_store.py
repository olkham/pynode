"""Encrypted credential store.

Node config never holds secrets. It holds a credential ID, and the secret
lives in ``credentials.json`` next to ``workflow.json``, encrypted with
Fernet (from ``cryptography``). Only fields that a credential type marks as
secret are encrypted, so listing credentials never needs the key.

The key is resolved in this order (first match wins):

1. ``PYNODE_CREDENTIAL_KEY``: a Fernet key,
2. ``PYNODE_CREDENTIAL_KEY_FILE``: the path to a file holding one,
3. ``<workflows dir>/.credential_key``: generated on first use, but only
   while the store holds no encrypted data yet.

The store fails loudly instead of guessing. A missing or wrong key raises
``CredentialError`` for anything that reads or stores a secret, and nothing
is written in that case, so a new key can never be mixed into an existing
store. Renames and deletes need no key; deleting the last secret also drops
the key check, so a store whose key was lost can start over.
"""

import copy
import json
import logging
import os
import threading
import uuid
from typing import Any
from collections.abc import Mapping

from cryptography.fernet import Fernet, InvalidToken

from pynode.config import ENV_CREDENTIAL_KEY, ENV_CREDENTIAL_KEY_FILE

logger = logging.getLogger(__name__)

# File names inside the workflows directory.
CREDENTIALS_FILE_NAME = 'credentials.json'
KEY_FILE_NAME = '.credential_key'


class CredentialError(Exception):
    """A credential cannot be stored or resolved.

    Raised for a missing credential, a locked store (no key), a wrong key or
    an unreadable store file. Messages name the credential or file and the
    cause, and never contain a secret value or a key.
    """


def _fernet(key_text: str, source: str) -> Fernet:
    """Build a Fernet from key text. On failure, name ``source``, never the key."""
    try:
        return Fernet(key_text.strip().encode('ascii'))
    except ValueError:
        raise CredentialError(f"{source} does not hold a valid Fernet key") from None


def _read_key_file(path: str) -> str:
    try:
        with open(path, encoding='ascii') as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise CredentialError(
            f"Cannot read credential key file {path}: {e.__class__.__name__}") from None


class CredentialKey:
    """Resolves the Fernet key for one credential store.

    Nothing is cached, so a key supplied after start-up (env var or key file)
    is picked up by the next call.
    """

    def __init__(self, default_key_file: str, environ: Mapping[str, str] | None = None):
        self.default_key_file = default_key_file
        # None = read os.environ at call time (tests pass a plain dict).
        self._environ = environ

    def get(self, create: bool = False) -> Fernet:
        """Return the active key.

        Args:
            create: allow generating the default key file when no key exists.
                Only the store passes True, and only while it holds no
                encrypted data; otherwise a fresh key would orphan every
                stored secret.

        Raises:
            CredentialError: the key is missing, unreadable or malformed.
        """
        environ = os.environ if self._environ is None else self._environ

        env_key = (environ.get(ENV_CREDENTIAL_KEY) or '').strip()
        if env_key:
            return _fernet(env_key, ENV_CREDENTIAL_KEY)

        key_file = (environ.get(ENV_CREDENTIAL_KEY_FILE) or '').strip()
        if key_file:
            key_file = os.path.abspath(os.path.expanduser(key_file))
            if not os.path.isfile(key_file):
                raise CredentialError(
                    f"Credential key file not found: {key_file} (set by {ENV_CREDENTIAL_KEY_FILE})")
            return _fernet(_read_key_file(key_file), key_file)

        if os.path.isfile(self.default_key_file):
            return _fernet(_read_key_file(self.default_key_file), self.default_key_file)

        if not create:
            raise CredentialError(
                f"Credential store is locked: no key. Set {ENV_CREDENTIAL_KEY} or "
                f"{ENV_CREDENTIAL_KEY_FILE}, or restore {self.default_key_file}")
        return _fernet(self._generate_default_key_file(), self.default_key_file)

    def _generate_default_key_file(self) -> str:
        """Create the default key file, owner-only where the OS supports it.

        O_EXCL guarantees an existing key file is never overwritten, even if
        another process creates one between the caller's check and this call.
        """
        directory = os.path.dirname(self.default_key_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        key = Fernet.generate_key().decode('ascii')
        try:
            fd = os.open(self.default_key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return _read_key_file(self.default_key_file)
        with os.fdopen(fd, 'w', encoding='ascii') as f:
            f.write(key)
        logger.warning(
            f"Generated credential key at {self.default_key_file}. Back it up together "
            f"with {CREDENTIALS_FILE_NAME}: without it the stored secrets cannot be "
            f"decrypted. Set {ENV_CREDENTIAL_KEY} or {ENV_CREDENTIAL_KEY_FILE} to keep "
            f"the key outside the data directory.")
        return key


STORE_VERSION = 1

# Encrypted under the active key when the first secret is stored. Decrypting
# it proves the key is the one that encrypted this store before any read or
# write touches a secret.
_KEY_CHECK_PLAINTEXT = b'pynode-credential-store'

# Credential types: {type name: {'type', 'label', 'fields': [{'name', 'label',
# 'secret'}]}}. Process-wide and static, like the node-type registries. Node
# packages add their own with register_credential_type().
CREDENTIAL_TYPES: dict[str, dict[str, Any]] = {}


def register_credential_type(type_name: str, label: str, fields: list[dict[str, Any]]) -> None:
    """Register (or replace) a credential type.

    Args:
        type_name: identifier stored with each credential and referenced by a
            node property's ``credentialType``.
        label: human-readable name for the editor.
        fields: ``[{'name': str, 'label': str, 'secret': bool}, ...]``. Secret
            fields are encrypted at rest and never returned by the API.
    """
    names = [field.get('name') for field in fields]
    if not names or not all(names) or len(set(names)) != len(names):
        raise ValueError(f"Credential type '{type_name}' needs unique, non-empty field names")
    CREDENTIAL_TYPES[type_name] = {
        'type': type_name,
        'label': label,
        'fields': [
            {'name': field['name'], 'label': field.get('label', field['name']),
             'secret': bool(field.get('secret', False))}
            for field in fields
        ],
    }


def list_credential_types() -> list[dict[str, Any]]:
    """Every registered credential type (copies, safe to serialise or mutate)."""
    return copy.deepcopy(list(CREDENTIAL_TYPES.values()))


# Core ships one type: a single secret value (an API token, a password, or a
# 'user:password' string for basic auth).
register_credential_type('secret', 'Secret', [
    {'name': 'value', 'label': 'Secret', 'secret': True},
])


class CredentialStore:
    """Encrypted credentials, referenced by ID from node config.

    One instance per app (``app.extensions['credential_store']``); nodes
    reach it through their engine (``BaseNode.get_credential``). The file is
    read lazily on first use, so building a store never touches the disk.

    File format::

        {"version": 1,
         "keyCheck": "<Fernet token>",      # present while a secret is stored
         "credentials": [{"id", "name", "type",
                          "fields":  {non-secret name: value},
                          "secrets": {secret name: Fernet token}}]}

    The fields/secrets split is decided when a value is written, so a
    listing never depends on the type registry to know what is secret.
    """

    def __init__(self, path: str, key_file: str | None = None,
                 environ: Mapping[str, str] | None = None):
        self.path = path
        self.key = CredentialKey(
            key_file or os.path.join(os.path.dirname(path), KEY_FILE_NAME), environ)
        # Guards _data and the file: API threads and node worker threads
        # call into the same store.
        self._lock = threading.RLock()
        self._data: dict[str, Any] | None = None

    # -- public API ---------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        """Public view of every credential (never includes a secret value)."""
        with self._lock:
            return [_public(entry) for entry in self._load()['credentials']]

    def get(self, cred_id: str) -> dict[str, Any] | None:
        """Public view of one credential, or None if it does not exist."""
        with self._lock:
            entry = _find(self._load(), cred_id)
            return _public(entry) if entry else None

    def create(self, name: str, type_name: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        """Create a credential and return its public view.

        Raises:
            ValueError: invalid name, type or fields (a client error).
            CredentialError: the key is missing or wrong, or the store is unreadable.
        """
        name = _clean_name(name)
        type_def = CREDENTIAL_TYPES.get(type_name) if isinstance(type_name, str) else None
        if type_def is None:
            raise ValueError(f"Unknown credential type: {type_name!r}")
        values = _check_fields(type_def, fields)
        entry: dict[str, Any] = {'id': uuid.uuid4().hex, 'name': name, 'type': type_name,
                                 'fields': {}, 'secrets': {}}
        secrets: dict[str, str] = {}
        for field in type_def['fields']:
            value = values.get(field['name'], '')
            if field['secret']:
                if not value:
                    raise ValueError(f"'{field['label']}' is required")
                secrets[field['name']] = value
            else:
                entry['fields'][field['name']] = value
        with self._lock:
            data = copy.deepcopy(self._load())
            if secrets:
                fernet = self._fernet_for_write(data)
                entry['secrets'] = {k: _encrypt(fernet, v) for k, v in secrets.items()}
            data['credentials'].append(entry)
            self._write(data)
            return _public(entry)

    def update(self, cred_id: str, name: str | None = None,
               fields: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        """Rename a credential and/or change its fields; None if it does not exist.

        A secret field that is missing or empty keeps its stored value, so the
        editor can save without ever having seen the secret. The type cannot
        change.

        Raises:
            ValueError: invalid name or fields (a client error).
            CredentialError: the key is missing or wrong, or the store is unreadable.
        """
        with self._lock:
            data = copy.deepcopy(self._load())
            entry = _find(data, cred_id)
            if entry is None:
                return None
            if name is not None:
                entry['name'] = _clean_name(name)
            if fields:
                type_def = CREDENTIAL_TYPES.get(entry['type'])
                if type_def is None:
                    raise ValueError(f"Credential type {entry['type']!r} is not installed")
                values = _check_fields(type_def, fields)
                new_secrets: dict[str, str] = {}
                for field in type_def['fields']:
                    if field['name'] not in values:
                        continue
                    value = values[field['name']]
                    if field['secret']:
                        if value:
                            new_secrets[field['name']] = value
                    else:
                        entry.setdefault('fields', {})[field['name']] = value
                if new_secrets:
                    fernet = self._fernet_for_write(data)
                    entry.setdefault('secrets', {}).update(
                        {k: _encrypt(fernet, v) for k, v in new_secrets.items()})
            self._write(data)
            return _public(entry)

    def delete(self, cred_id: str) -> bool:
        """Delete a credential; False if it does not exist. Callers check usage first."""
        with self._lock:
            data = copy.deepcopy(self._load())
            entry = _find(data, cred_id)
            if entry is None:
                return False
            data['credentials'].remove(entry)
            # With no secret left there is nothing a key could orphan: drop the
            # keyCheck so a store whose key was lost can start over with a new key.
            if not any(e.get('secrets') for e in data['credentials']):
                data.pop('keyCheck', None)
            self._write(data)
            return True

    def resolve(self, cred_id: str) -> dict[str, str]:
        """Every field of a credential, with secret fields decrypted.

        Raises:
            CredentialError: not found, store locked, wrong key or unreadable store.
        """
        with self._lock:
            data = self._load()
            entry = _find(data, cred_id)
            if entry is None:
                raise CredentialError(f"Credential '{cred_id}' not found")
            values = dict(entry.get('fields', {}))
            tokens = entry.get('secrets', {})
            if tokens:
                try:
                    fernet = self._fernet_for_read(data)
                except CredentialError as e:
                    raise CredentialError(f"Credential '{entry['name']}' ({cred_id}): {e}") from None
                for field_name, token in tokens.items():
                    try:
                        values[field_name] = fernet.decrypt(token.encode('ascii')).decode('utf-8')
                    except (InvalidToken, ValueError, AttributeError):
                        raise CredentialError(
                            f"Credential '{entry.get('name')}' ({cred_id}) cannot be "
                            f"decrypted with the current key") from None
            return values

    # -- internals ----------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        """The store contents, read from disk on first use.

        An unreadable file raises CredentialError on every call and is never
        overwritten, because every write starts from a successful load.
        """
        if self._data is None:
            if not os.path.exists(self.path):
                self._data = {'version': STORE_VERSION, 'credentials': []}
            else:
                try:
                    with open(self.path, encoding='utf-8') as f:
                        data = json.load(f)
                except (OSError, ValueError) as e:
                    raise CredentialError(f"Cannot read credential store {self.path}: {e}") from None
                if (not isinstance(data, dict)
                        or not isinstance(data.get('credentials'), list)
                        or not isinstance(data.get('keyCheck', ''), str)
                        or not all(_valid_entry(entry) for entry in data['credentials'])):
                    raise CredentialError(f"Cannot read credential store {self.path}: unexpected format")
                self._data = data
        return self._data

    def _write(self, data: dict[str, Any]) -> None:
        """Atomically replace the file, then adopt ``data`` as the in-memory state.

        Callers mutate a deep copy and pass it here, so a failed write leaves
        both the file and the in-memory state as they were.
        """
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = self.path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, self.path)
        self._data = data

    def _fernet_for_write(self, data: dict[str, Any]) -> Fernet:
        """Key for encrypting into ``data``; stamps keyCheck when the first secret is stored."""
        if data.get('keyCheck'):
            fernet = self.key.get(create=False)
            self._verify_key(fernet, data)
            return fernet
        if any(entry.get('secrets') for entry in data['credentials']):
            raise CredentialError(f"{self.path} holds secrets but no keyCheck (edited by hand?)")
        fernet = self.key.get(create=True)
        data['keyCheck'] = _encrypt(fernet, _KEY_CHECK_PLAINTEXT.decode('ascii'))
        return fernet

    def _fernet_for_read(self, data: dict[str, Any]) -> Fernet:
        if not data.get('keyCheck'):
            raise CredentialError(f"{self.path} holds secrets but no keyCheck (edited by hand?)")
        fernet = self.key.get(create=False)
        self._verify_key(fernet, data)
        return fernet

    def _verify_key(self, fernet: Fernet, data: dict[str, Any]) -> None:
        try:
            matches = fernet.decrypt(data['keyCheck'].encode('ascii')) == _KEY_CHECK_PLAINTEXT
        except (InvalidToken, ValueError, AttributeError):
            matches = False
        if not matches:
            raise CredentialError(
                f"The credential key does not match {self.path}. Check {ENV_CREDENTIAL_KEY}, "
                f"{ENV_CREDENTIAL_KEY_FILE} and {self.key.default_key_file}")


def _encrypt(fernet: Fernet, value: str) -> str:
    return fernet.encrypt(value.encode('utf-8')).decode('ascii')


def _find(data: dict[str, Any], cred_id: str) -> dict[str, Any] | None:
    for entry in data['credentials']:
        if entry.get('id') == cred_id:
            return entry
    return None


def _public(entry: dict[str, Any]) -> dict[str, Any]:
    """The client-safe view of a stored credential.

    Built from the file's own fields/secrets split, not from the type
    registry, so a credential whose type's package was uninstalled still
    never exposes a secret.
    """
    return {
        'id': entry['id'],
        'name': entry['name'],
        'type': entry['type'],
        'fields': dict(entry.get('fields', {})),
        'secretsSet': sorted(entry.get('secrets', {})),
    }


def _valid_entry(entry: Any) -> bool:
    """True when a stored credential has the shape this module writes."""
    if not isinstance(entry, dict):
        return False
    if not all(isinstance(entry.get(key), str) for key in ('id', 'name', 'type')):
        return False
    for key in ('fields', 'secrets'):
        value = entry.get(key, {})
        if not isinstance(value, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            return False
    return True


def _clean_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Credential name is required')
    return name.strip()


def _check_fields(type_def: dict[str, Any], fields: Any) -> dict[str, str]:
    """Validate submitted field values against a type and return them as a plain dict.

    Error messages name fields, never values.
    """
    if not isinstance(fields, Mapping):
        raise ValueError('fields must be an object')
    known = {field['name'] for field in type_def['fields']}
    for field_name, value in fields.items():
        if field_name not in known:
            raise ValueError(f"Unknown field for credential type '{type_def['type']}': {field_name!r}")
        if not isinstance(value, str):
            raise ValueError(f"Field {field_name!r} must be a string")
    return dict(fields)
