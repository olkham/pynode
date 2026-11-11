// MQTT broker (service) management.
//
// Two responsibilities:
//   1. Populate the compact broker <select> shown in a node's properties panel
//      (rendered by properties.js for the `mqtt-service` property type).
//   2. Drive the single "Manage MQTT Brokers" dialog (one overlay in
//      index.html, #mqtt-broker-dialog) where the user can pick an existing
//      broker OR start a new one, edit every field, test the connection, save,
//      and delete - all in one place.
//
// The broker password is a stored credential (see credentials.js): the form
// holds only a credential ID, and the server never returns a password. A
// broker saved before the credential store may still have a plain-text
// password (`hasPassword`); it keeps working until a credential replaces it.
//
// All API calls go through the global fetch() which auth.js transparently
// decorates with the API key, so plain fetch(`${API_BASE}/...`) is correct.
import { state, markNodeModified, setModified } from './state.js';
import { API_BASE } from './config.js';
import { showToast } from './ui-utils.js';

// Which node/property the dialog is currently editing brokers for.
let dialogContext = { nodeId: null, propName: null };

// True once the user asked to drop the broker's legacy plain-text password;
// applied by the next save (or test) of the form.
let removeLegacyPassword = false;

const PASSWORD_CREDENTIAL_TYPE = 'secret';

// Show or hide the "saved in plain text" note for the broker in the form.
function setLegacyPassword(kept) {
    removeLegacyPassword = false;
    const note = document.getElementById('mqtt-broker-legacy-password');
    if (note) note.style.display = kept ? '' : 'none';
}

function loadPasswordCredentials(currentId) {
    return window.fillCredentialSelect(
        document.getElementById('mqtt-broker-credential'),
        PASSWORD_CREDENTIAL_TYPE, currentId, '-- No password --');
}

// -------------------------------------------------------------------------
// Compact per-node broker <select>
// -------------------------------------------------------------------------

// Populate a node property's broker <select> with the available services.
// A serviceId that no longer resolves to a known broker is shown as
// "(missing broker)" so a dangling reference is visible rather than silent.
window.loadMqttServices = async function (nodeId, propName, currentServiceId) {
    const select = document.getElementById(`mqtt-service-${nodeId}`);
    if (!select) return;
    try {
        const response = await fetch(`${API_BASE}/services/mqtt`);
        const data = await response.json();
        if (!data.success) {
            console.error('Failed to load MQTT services:', data.error);
            return;
        }

        select.innerHTML = '<option value="">-- Select broker --</option>';
        let matched = false;
        data.services.forEach(service => {
            const option = document.createElement('option');
            option.value = service.id;
            option.textContent = `${service.name} (${service.broker}:${service.port})`;
            if (service.id === currentServiceId) {
                option.selected = true;
                matched = true;
            }
            select.appendChild(option);
        });

        // Dangling reference: keep the id assigned but flag it in the UI.
        if (currentServiceId && !matched) {
            const option = document.createElement('option');
            option.value = currentServiceId;
            option.textContent = '(missing broker)';
            option.selected = true;
            select.appendChild(option);
        }
    } catch (error) {
        console.error('Error loading MQTT services:', error);
    }
};

// Node's compact select changed -> assign the chosen broker to the node.
window.onMqttServiceSelect = function (nodeId, propName, serviceId) {
    const nodeData = state.nodes.get(nodeId);
    if (!nodeData) return;
    nodeData.config[propName] = serviceId;
    markNodeModified(nodeId);
    setModified(true);
};

// -------------------------------------------------------------------------
// "Manage MQTT Brokers" dialog
// -------------------------------------------------------------------------

function dialogEl() {
    return document.getElementById('mqtt-broker-dialog');
}

function fieldValue(id) {
    const el = document.getElementById(id);
    return el ? el.value : '';
}

function setField(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
}

function clearTestResult() {
    const box = document.getElementById('mqtt-broker-test-result');
    if (box) {
        box.style.display = 'none';
        box.textContent = '';
        box.className = 'mqtt-test-result';
    }
}

function showTestResult(ok, message) {
    const box = document.getElementById('mqtt-broker-test-result');
    if (!box) return;
    box.style.display = 'block';
    box.className = 'mqtt-test-result ' + (ok ? 'success' : 'error');
    box.textContent = (ok ? '✓ ' : '✗ ') + message;
}

// Read the current form values into a service config object. There is no
// password in it: `credential` names the stored secret, and leaving out the
// `password` key keeps a legacy plain-text password on the server.
function readForm() {
    const config = {
        name: fieldValue('mqtt-broker-name').trim(),
        broker: fieldValue('mqtt-broker-host').trim(),
        port: parseInt(fieldValue('mqtt-broker-port'), 10) || 1883,
        clientId: fieldValue('mqtt-broker-clientId').trim(),
        username: fieldValue('mqtt-broker-username'),
        credential: fieldValue('mqtt-broker-credential'),
        keepAlive: parseInt(fieldValue('mqtt-broker-keepAlive'), 10) || 60,
        cleanSession: fieldValue('mqtt-broker-cleanSession') !== 'false'
    };
    if (removeLegacyPassword) config.password = '';
    return config;
}

// Reset the form to a blank "new broker" state.
function resetForm() {
    setField('mqtt-broker-id', '');
    setField('mqtt-broker-name', '');
    setField('mqtt-broker-host', 'localhost');
    setField('mqtt-broker-port', '1883');
    setField('mqtt-broker-clientId', '');
    setField('mqtt-broker-username', '');
    setField('mqtt-broker-keepAlive', '60');
    setField('mqtt-broker-cleanSession', 'true');
    setLegacyPassword(false);
    loadPasswordCredentials('');
    const delBtn = document.getElementById('mqtt-broker-delete-btn');
    if (delBtn) delBtn.style.display = 'none';
    clearTestResult();
}

// Load a saved broker's full config into the form.
async function loadBrokerIntoForm(serviceId) {
    clearTestResult();
    if (!serviceId || serviceId === '__new__') {
        resetForm();
        return;
    }
    try {
        const response = await fetch(`${API_BASE}/services/mqtt/${serviceId}`);
        const data = await response.json();
        if (data.success && data.service) {
            const s = data.service;
            setField('mqtt-broker-id', s.id || '');
            setField('mqtt-broker-name', s.name || '');
            setField('mqtt-broker-host', s.broker || 'localhost');
            setField('mqtt-broker-port', s.port != null ? s.port : 1883);
            setField('mqtt-broker-clientId', s.clientId || '');
            setField('mqtt-broker-username', s.username || '');
            setLegacyPassword(Boolean(s.hasPassword) && !s.credential);
            await loadPasswordCredentials(s.credential || '');
            setField('mqtt-broker-keepAlive', s.keepAlive != null ? s.keepAlive : 60);
            setField('mqtt-broker-cleanSession', s.cleanSession === false ? 'false' : 'true');
            const delBtn = document.getElementById('mqtt-broker-delete-btn');
            if (delBtn) delBtn.style.display = '';
        } else {
            resetForm();
        }
    } catch (error) {
        console.error('Error loading MQTT service:', error);
        resetForm();
    }
}

// Populate the broker picker <select> at the top of the dialog.
async function loadPicker(selectedId) {
    const picker = document.getElementById('mqtt-broker-picker');
    if (!picker) return [];
    let services = [];
    try {
        const response = await fetch(`${API_BASE}/services/mqtt`);
        const data = await response.json();
        if (data.success) services = data.services;
    } catch (error) {
        console.error('Error loading MQTT services:', error);
    }
    picker.innerHTML = '<option value="__new__">➕ New broker…</option>';
    services.forEach(service => {
        const option = document.createElement('option');
        option.value = service.id;
        option.textContent = `${service.name} (${service.broker}:${service.port})`;
        if (service.id === selectedId) option.selected = true;
        picker.appendChild(option);
    });
    if (selectedId && !services.some(s => s.id === selectedId)) {
        picker.value = '__new__';
    }
    return services;
}

// Open the dialog for a given node/property. Preselects the node's current
// broker if it still exists, otherwise starts on "New broker".
window.openMqttBrokerDialog = async function (nodeId, propName) {
    dialogContext = { nodeId, propName };
    const overlay = dialogEl();
    if (!overlay) return;
    overlay.dataset.nodeId = nodeId;
    overlay.dataset.propName = propName;

    const nodeData = state.nodes.get(nodeId);
    const currentServiceId = (nodeData && nodeData.config[propName]) || '';

    const services = await loadPicker(currentServiceId);
    const exists = currentServiceId && services.some(s => s.id === currentServiceId);
    await loadBrokerIntoForm(exists ? currentServiceId : '__new__');

    overlay.style.display = 'flex';
};

// Picker changed -> load that broker (or a blank new form) into the fields.
window.onMqttBrokerPick = function (serviceId) {
    loadBrokerIntoForm(serviceId);
};

window.closeMqttBrokerDialog = function () {
    const overlay = dialogEl();
    if (overlay) overlay.style.display = 'none';
    clearTestResult();
};

// Manage stored credentials from inside the broker dialog. The credential
// dialog is later in the DOM, so it stacks above this one.
window.openMqttBrokerCredentialDialog = function () {
    return window.openCredentialDialogFor({
        credentialType: PASSWORD_CREDENTIAL_TYPE,
        getCurrent: () => fieldValue('mqtt-broker-credential'),
        // Only fills the form: the broker is saved with its own Save button.
        assign: credentialId => loadPasswordCredentials(credentialId)
    });
};

// Drop the legacy plain-text password when the broker is next saved.
window.removeMqttBrokerLegacyPassword = function () {
    setLegacyPassword(false);
    removeLegacyPassword = true;
};

// Test the connection using the CURRENT form values (never a saved service).
// The server fills in the password: from the selected credential or, for a
// saved broker without one, from its legacy stored password.
window.testMqttBroker = async function () {
    const config = readForm();
    config.id = fieldValue('mqtt-broker-id');
    if (!config.broker) {
        showTestResult(false, 'Enter a broker address first.');
        return;
    }
    const btn = document.getElementById('mqtt-broker-test-btn');
    const box = document.getElementById('mqtt-broker-test-result');
    if (box) {
        box.style.display = 'block';
        box.className = 'mqtt-test-result testing';
        box.textContent = '… Testing connection…';
    }
    if (btn) btn.disabled = true;
    try {
        const response = await fetch(`${API_BASE}/services/mqtt/test`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        const data = await response.json();
        if (data.success) {
            showTestResult(true, 'Connection successful.');
        } else {
            showTestResult(false, data.error || 'Connection failed.');
        }
    } catch (error) {
        console.error('Error testing MQTT connection:', error);
        showTestResult(false, 'Request failed. Is the server reachable?');
    } finally {
        if (btn) btn.disabled = false;
    }
};

// Create (POST) or update (PUT) the broker, then assign it to the node.
window.saveMqttBroker = async function () {
    const serviceId = fieldValue('mqtt-broker-id');
    const config = readForm();
    if (!config.name) {
        showTestResult(false, 'Enter a name for the broker.');
        return;
    }
    if (!config.broker) {
        showTestResult(false, 'Enter a broker address.');
        return;
    }
    try {
        let response;
        if (serviceId) {
            response = await fetch(`${API_BASE}/services/mqtt/${serviceId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
        } else {
            response = await fetch(`${API_BASE}/services/mqtt`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
        }
        const data = await response.json();
        if (!data.success || !data.service) {
            showTestResult(false, 'Failed to save: ' + (data.error || 'Unknown error'));
            return;
        }

        const savedId = data.service.id;
        // Assign the saved broker to the node that opened the dialog.
        const { nodeId, propName } = dialogContext;
        const nodeData = nodeId && state.nodes.get(nodeId);
        if (nodeData) {
            nodeData.config[propName] = savedId;
            markNodeModified(nodeId);
            setModified(true);
            await window.loadMqttServices(nodeId, propName, savedId);
        }
        // Keep the dialog open on the just-saved broker so the user can keep
        // managing; refresh the picker to reflect any new entry / rename.
        await loadPicker(savedId);
        await loadBrokerIntoForm(savedId);
        showToast('Broker saved');
    } catch (error) {
        console.error('Error saving MQTT service:', error);
        showTestResult(false, 'Error saving broker.');
    }
};

// Delete the currently selected broker.
window.deleteMqttBroker = async function () {
    const serviceId = fieldValue('mqtt-broker-id');
    if (!serviceId) return;
    if (!confirm('Delete this broker configuration?')) return;
    try {
        const response = await fetch(`${API_BASE}/services/mqtt/${serviceId}`, {
            method: 'DELETE'
        });
        const data = await response.json();
        if (!data.success) {
            showTestResult(false, 'Failed to delete: ' + (data.error || 'Broker may still be in use'));
            return;
        }

        // If the deleted broker was assigned to the node, clear the assignment.
        const { nodeId, propName } = dialogContext;
        const nodeData = nodeId && state.nodes.get(nodeId);
        if (nodeData && nodeData.config[propName] === serviceId) {
            nodeData.config[propName] = '';
            markNodeModified(nodeId);
            setModified(true);
            await window.loadMqttServices(nodeId, propName, '');
        }
        await loadPicker('__new__');
        await loadBrokerIntoForm('__new__');
        showToast('Broker deleted');
    } catch (error) {
        console.error('Error deleting MQTT service:', error);
        showTestResult(false, 'Error deleting broker.');
    }
};
