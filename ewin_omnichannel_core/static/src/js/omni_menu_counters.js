/** @odoo-module **/

import { registry } from "@web/core/registry";
import { debounce } from "@web/core/utils/timing";
import { reactive } from "@odoo/owl";

/**
 * Holds the two numbers the EWIN Inbox menu badges wear.
 *
 * It asks the server for nothing until the navbar says the app is on screen:
 * the badges live on that app's own menus, so a user working in Sales pays
 * nothing for this. While the app IS open the server pushes
 * "omni.menu.counters" whenever anything in the inbox moves, and that is what
 * keeps the numbers honest without a poll.
 */
export const omniMenuCountersService = {
    dependencies: ["orm", "bus_service"],
    start(env, { orm, bus_service }) {
        const counters = reactive({ unassigned: 0, mine: 0 });
        let active = false;

        const fetch = async () => {
            if (!active) {
                return;
            }
            Object.assign(
                counters,
                await orm.call("omnichannel.conversation", "omni_menu_counters", [])
            );
        };
        // A burst of inbound messages is one refresh, not one per message.
        const refresh = debounce(fetch, 300);
        bus_service.subscribe("omni.menu.counters", refresh);

        return {
            counters,
            /** Called by the navbar: true while EWIN Inbox is the open app. */
            setActive(value) {
                if (value === active) {
                    return;
                }
                active = value;
                if (active) {
                    fetch();
                } else {
                    // Nothing is watching. Dropping the numbers keeps a stale
                    // badge from being the first thing seen on the way back in,
                    // before the fresh count lands.
                    counters.unassigned = 0;
                    counters.mine = 0;
                }
            },
        };
    },
};

registry.category("services").add("omni_menu_counters", omniMenuCountersService);
