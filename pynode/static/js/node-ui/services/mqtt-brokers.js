// MQTT broker (service) management.
//
// A shared service, not a node's own UI: brokers are global config
// (/api/services/mqtt, mqtt_services.json) that any node could reference. The
// `mqtt-service` property editor that consumes this lives with the node that
// declares it, in pynode/nodes/MQTTNode/ui/.
//
// Two responsibilities:
//   1. Populate the compact broker <select> a node's property editor renders.
//   2. Drive the single "Manage MQTT Brokers" dialog (one overlay in
//      index.html, #mqtt-broker-dialog) where the user can pick an existing
//      broker OR start a new one, edit every field, test the connection, save,
//      and delete - all in one place.
//
// The dialog keeps window.* handlers because index.html's markup wires its
// buttons with inline onclick; that markup is the remaining piece to move.
//
// All API calls go through the global fetch() which auth.js transparently
// decorates with the API key, so plain fetch(`${API_BASE}/...`) is correct.
import { API_BASE } from '../../config.js';
import { showToast } from '../../ui-utils.js';

// How the dialog writes back to whatever opened it: `assign` receives a
// broker id (or '' to clear) and `current` reports the id in use, so the
// dialog never needs to know which node or property it is editing.
let dialogContext = { current: () => '', assign: () => {} };

// -------------------------------------------------------------------------
// Compact per-node broker <select>
// -------------------------------------------------------------------------

// Populate a node property's broker <select> with the available services.
// A serviceId that no longer resolves to a known broker is shown as
// "(missing broker)" so a dangling reference is visible rather than silent.
export async function populateBrokerSelect(select, currentServiceId) {
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
}

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

// Read the current form values into a service config object.
function readForm() {
    return {
        name: fieldValue('mqtt-broker-name').trim(),
        broker: fieldValue('mqtt-broker-host').trim(),
        port: parseInt(fieldValue('mqtt-broker-port'), 10) || 1883,
        clientId: fieldValue('mqtt-broker-clientId').trim(),
        username: fieldValue('mqtt-broker-username'),
        password: fieldValue('mqtt-broker-password'),
        keepAlive: parseInt(fieldValue('mqtt-broker-keepAlive'), 10) || 60,
        cleanSession: fieldValue('mqtt-broker-cleanSession') !== 'false'
    };
}

// Reset the form to a blank "new broker" state.
function resetForm() {
    setField('mqtt-broker-id', '');
    setField('mqtt-broker-name', '');
    setField('mqtt-broker-host', 'localhost');
    setField('mqtt-broker-port', '1883');
    setField('mqtt-broker-clientId', '');
    setField('mqtt-broker-username', '');
    setField('mqtt-broker-password', '');
    setField('mqtt-broker-keepAlive', '60');
    setField('mqtt-broker-cleanSession', 'true');
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
            setField('mqtt-broker-password', s.password || '');
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

/**
 * Open the broker manager. Preselects the broker currently in use if it still
 * exists, otherwise starts on "New broker".
 *
 * @param {object} args
 * @param {() => string} args.current - the broker id in use right now
 * @param {(serviceId: string) => void} args.assign - called when the dialog
 *        assigns a saved broker, or clears one it deleted
 */
export async function openMqttBrokerDialog({ current, assign }) {
    dialogContext = { current, assign };
    const overlay = dialogEl();
    if (!overlay) return;

    const currentServiceId = current() || '';
    const services = await loadPicker(currentServiceId);
    const exists = currentServiceId && services.some(s => s.id === currentServiceId);
    await loadBrokerIntoForm(exists ? currentServiceId : '__new__');

    overlay.style.display = 'flex';
}

// Picker changed -> load that broker (or a blank new form) into the fields.
window.onMqttBrokerPick = function (serviceId) {
    loadBrokerIntoForm(serviceId);
};

window.closeMqttBrokerDialog = function () {
    const overlay = dialogEl();
    if (overlay) overlay.style.display = 'none';
    clearTestResult();
};

// Test the connection using the CURRENT form values (never a saved service).
window.testMqttBroker = async function () {
    const config = readForm();
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
        // Assign the saved broker back to whatever opened the dialog.
        dialogContext.assign(savedId);
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

        // If the deleted broker was the one in use, clear the assignment.
        if (dialogContext.current() === serviceId) {
            dialogContext.assign('');
        }
        await loadPicker('__new__');
        await loadBrokerIntoForm('__new__');
        showToast('Broker deleted');
    } catch (error) {
        console.error('Error deleting MQTT service:', error);
        showTestResult(false, 'Error deleting broker.');
    }
};
