// Credential store UI.
//
// Two responsibilities, mirroring mqtt-services.js:
//   1. Populate the compact credential <select> that properties.js renders
//      for the `credential` property type (only credentials of the property's
//      credentialType are offered).
//   2. Drive the "Manage Credentials" dialog (#credential-dialog in
//      index.html): pick or create a credential, rename it, replace its
//      secret, delete it.
//
// The dialog edits credentials for a "target": something that holds one
// credential ID. A node property is the usual target; other owners (the MQTT
// broker dialog) open it with window.openCredentialDialogFor().
//
// The server never returns secret values, so secret inputs always start
// empty and a blank secret on save keeps the stored value. DOM built from
// server data uses createElement/textContent, never innerHTML.
// All API calls go through the global fetch() that auth.js decorates with
// the API key.
import { state, markNodeModified, setModified } from './state.js';
import { API_BASE } from './config.js';
import { showToast } from './ui-utils.js';

// What the dialog is editing for: the credential type on offer, plus how to
// read (getCurrent) and write (assign) the target's credential ID.
let dialogContext = { credentialType: null, getCurrent: () => '', assign: async () => {} };
let typesCache = null;

async function fetchJson(url, options) {
    const response = await fetch(url, options);
    return response.json();
}

async function loadTypes() {
    if (!typesCache) {
        const data = await fetchJson(`${API_BASE}/credential-types`);
        typesCache = data.success ? data.types : [];
    }
    return typesCache;
}

async function loadCredentials(credentialType) {
    const data = await fetchJson(`${API_BASE}/credentials`);
    if (!data.success) throw new Error(data.error || 'Failed to load credentials');
    return data.credentials.filter(c => c.type === credentialType);
}

function addOption(select, value, text, selected) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = text;
    option.selected = Boolean(selected);
    select.appendChild(option);
}

// -------------------------------------------------------------------------
// Compact per-node credential <select>
// -------------------------------------------------------------------------

// Fill any <select> with the credentials of one type. A reference that no
// longer resolves is shown as "(missing credential)" so a dangling ID is
// visible rather than silent.
window.fillCredentialSelect = async function (select, credentialType, currentId, emptyLabel) {
    if (!select) return;
    try {
        const credentials = await loadCredentials(credentialType);
        select.replaceChildren();
        addOption(select, '', emptyLabel || '-- Select credential --', !currentId);
        credentials.forEach(c => addOption(select, c.id, c.name, c.id === currentId));
        if (currentId && !credentials.some(c => c.id === currentId)) {
            addOption(select, currentId, '(missing credential)', true);
        }
    } catch (error) {
        console.error('Error loading credentials:', error);
    }
};

window.loadCredentialOptions = function (nodeId, propName, credentialType, currentId) {
    const select = document.getElementById(`credential-${nodeId}-${propName}`);
    return window.fillCredentialSelect(select, credentialType, currentId);
};

window.onCredentialSelect = function (nodeId, propName, credentialId) {
    const nodeData = state.nodes.get(nodeId);
    if (!nodeData) return;
    nodeData.config[propName] = credentialId;
    markNodeModified(nodeId);
    setModified(true);
};

// -------------------------------------------------------------------------
// "Manage Credentials" dialog
// -------------------------------------------------------------------------

function showResult(ok, message) {
    const box = document.getElementById('credential-result');
    if (!box) return;
    box.style.display = message ? 'block' : 'none';
    box.className = 'mqtt-test-result ' + (ok ? 'success' : 'error');
    box.textContent = message ? (ok ? '✓ ' : '✗ ') + message : '';
}

// Build one input per field of the dialog's credential type. Secret fields
// are password inputs that always start empty.
async function renderFields(credential) {
    const container = document.getElementById('credential-fields');
    container.replaceChildren();
    const types = await loadTypes();
    const typeDef = types.find(t => t.type === dialogContext.credentialType);
    if (!typeDef) {
        showResult(false, `Unknown credential type: ${dialogContext.credentialType}`);
        return;
    }
    typeDef.fields.forEach(field => {
        const group = document.createElement('div');
        group.className = 'property-group';
        const label = document.createElement('label');
        label.className = 'property-label';
        label.textContent = field.label;
        const input = document.createElement('input');
        input.className = 'property-input';
        input.dataset.field = field.name;
        input.dataset.secret = field.secret ? 'true' : 'false';
        if (field.secret) {
            input.type = 'password';
            input.autocomplete = 'new-password';
            const isSet = Boolean(credential) && credential.secretsSet.includes(field.name);
            input.placeholder = isSet ? 'Set, leave blank to keep' : 'Required';
        } else {
            input.type = 'text';
            input.autocomplete = 'off';
            input.value = (credential && credential.fields[field.name]) || '';
        }
        group.append(label, input);
        container.appendChild(group);
    });
}

function readFields() {
    const fields = {};
    document.querySelectorAll('#credential-fields input').forEach(input => {
        // A blank secret means "keep the stored value": leave it out.
        if (input.dataset.secret === 'true' && input.value === '') return;
        fields[input.dataset.field] = input.value;
    });
    return fields;
}

async function loadIntoForm(credentialId, credentials) {
    showResult(true, '');
    const credential = credentials.find(c => c.id === credentialId) || null;
    document.getElementById('credential-id').value = credential ? credential.id : '';
    document.getElementById('credential-name').value = credential ? credential.name : '';
    document.getElementById('credential-delete-btn').style.display = credential ? '' : 'none';
    await renderFields(credential);
}

// Reload the picker and the form, selecting `selectedId` if it still exists.
async function refreshDialog(selectedId) {
    const picker = document.getElementById('credential-picker');
    const credentials = await loadCredentials(dialogContext.credentialType);
    const exists = Boolean(selectedId) && credentials.some(c => c.id === selectedId);
    picker.replaceChildren();
    addOption(picker, '__new__', '➕ New credential…', !exists);
    credentials.forEach(c => addOption(picker, c.id, c.name, exists && c.id === selectedId));
    await loadIntoForm(exists ? selectedId : null, credentials);
}

// Open the dialog for any target that holds one credential ID.
//   credentialType: the type on offer.
//   getCurrent():   the target's current credential ID ('' for none).
//   assign(id):     store a new ID on the target and refresh its own UI;
//                   called after a save (the saved ID) and after deleting
//                   the target's current credential ('').
window.openCredentialDialogFor = async function ({ credentialType, getCurrent, assign }) {
    dialogContext = { credentialType, getCurrent, assign };
    try {
        await refreshDialog(getCurrent() || '');
    } catch (error) {
        console.error('Error opening credential dialog:', error);
        showToast(error.message || 'Failed to load credentials', 'error');
        return;
    }
    document.getElementById('credential-dialog').style.display = 'flex';
};

// Open the dialog for a node's `credential` property.
window.openCredentialDialog = function (nodeId, propName, credentialType) {
    const nodeData = () => state.nodes.get(nodeId);
    return window.openCredentialDialogFor({
        credentialType,
        getCurrent: () => (nodeData() && nodeData().config[propName]) || '',
        assign: async credentialId => {
            if (!nodeData()) return;
            nodeData().config[propName] = credentialId;
            markNodeModified(nodeId);
            setModified(true);
            await window.loadCredentialOptions(nodeId, propName, credentialType, credentialId);
        }
    });
};

window.onCredentialPick = async function (credentialId) {
    try {
        const credentials = await loadCredentials(dialogContext.credentialType);
        await loadIntoForm(credentialId === '__new__' ? null : credentialId, credentials);
    } catch (error) {
        console.error('Error loading credential:', error);
        showResult(false, 'Error loading credential.');
    }
};

window.closeCredentialDialog = function () {
    // Drop any typed but unsaved secret instead of leaving it in the hidden dialog.
    document.getElementById('credential-fields').replaceChildren();
    document.getElementById('credential-dialog').style.display = 'none';
    showResult(true, '');
};

// Create (POST) or update (PUT), then assign the saved credential to the target.
window.saveCredential = async function () {
    const id = document.getElementById('credential-id').value;
    const name = document.getElementById('credential-name').value.trim();
    if (!name) {
        showResult(false, 'Enter a name.');
        return;
    }
    const body = { name, fields: readFields() };
    if (!id) body.type = dialogContext.credentialType;
    try {
        const data = await fetchJson(id ? `${API_BASE}/credentials/${id}` : `${API_BASE}/credentials`, {
            method: id ? 'PUT' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (!data.success) {
            showResult(false, data.error || 'Save failed.');
            return;
        }
        await dialogContext.assign(data.credential.id);
        await refreshDialog(data.credential.id);
        showToast('Credential saved');
    } catch (error) {
        console.error('Error saving credential:', error);
        showResult(false, 'Error saving credential.');
    }
};

// Delete the selected credential. The server refuses (409) while a deployed
// or saved node, or an MQTT broker, still uses it.
window.deleteCredential = async function () {
    const id = document.getElementById('credential-id').value;
    if (!id || !confirm('Delete this credential?')) return;
    try {
        const data = await fetchJson(`${API_BASE}/credentials/${id}`, { method: 'DELETE' });
        if (!data.success) {
            showResult(false, data.error || 'Delete failed.');
            return;
        }
        if (dialogContext.getCurrent() === id) await dialogContext.assign('');
        await refreshDialog(null);
        showToast('Credential deleted');
    } catch (error) {
        console.error('Error deleting credential:', error);
        showResult(false, 'Error deleting credential.');
    }
};
