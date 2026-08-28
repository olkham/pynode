// Properties editor for the MQTT nodes' `service` property.
//
// A compact select of the brokers already configured, plus one button that
// opens the shared broker manager (pick / create / edit / test / save / delete
// in one place). Brokers are global config, so the manager itself is a shared
// service; only this picker belongs to the node.

import { h, label } from '/js/node-ui/dom.js';
import { openMqttBrokerDialog, populateBrokerSelect } from '/js/node-ui/services/mqtt-brokers.js';

export default {
    propertyType: 'mqtt-service',

    mount(ctx) {
        const picker = h('select', {
            class: 'property-select property-service-select',
            onchange: e => ctx.set(e.target.value),
        }, h('option', { value: '' }, '-- Select broker --'));

        return h('div', {},
            label(ctx.prop.label),
            h('div', { class: 'property-service-container' },
                picker,
                h('button', {
                    class: 'btn btn-secondary property-service-btn property-service-manage',
                    type: 'button',
                    title: 'Add, edit, test or delete broker connections',
                    onclick: () => openMqttBrokerDialog({
                        current: () => ctx.value || '',
                        assign: async (serviceId) => {
                            ctx.set(serviceId);
                            await populateBrokerSelect(picker, serviceId);
                        },
                    }),
                }, 'Manage brokers…'),
            ),
        );
    },

    ready(el, ctx) {
        // Fills in the broker list; a stored id that no longer resolves shows
        // as "(missing broker)" rather than silently selecting the first entry.
        return populateBrokerSelect(el.querySelector('select'), ctx.value || '');
    },
};
