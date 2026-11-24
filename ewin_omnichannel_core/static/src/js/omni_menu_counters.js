import { Plugin, proxy, usePlugin } from "@odoo/owl";
import { BusPlugin } from "@bus/services/bus_plugin";
import { ORM } from "@web/core/orm_plugin";
import { services } from "@web/core/services";
import { debounce } from "@web/core/utils/timing";

/**
 * Holds the two numbers the EWIN Inbox menu badges wear.
 *
 * It asks the server for nothing until the navbar says the app is on screen:
 * the badges live on that app's own menus, so a user working in Sales pays
 * nothing for this. While the app IS open the server pushes
 * "omni.menu.counters" whenever anything in the inbox moves, and that is what
 * keeps the numbers honest without a poll.
 */
export class OmniMenuCountersPlugin extends Plugin {
    orm = usePlugin(ORM);
    bus = usePlugin(BusPlugin);

    counters = proxy({ unassigned: 0, mine: 0 });
    active = false;

    setup() {
        // A burst of inbound messages is one refresh, not one per message.
        this.bus.subscribe("omni.menu.counters", debounce(() => this.fetch(), 300));
    }

    async fetch() {
        if (!this.active) {
            return;
        }
        Object.assign(
            this.counters,
            await this.orm.call("omnichannel.conversation", "omni_menu_counters", [])
        );
    }

    /** Called by the navbar: true while EWIN Inbox is the open app. */
    setActive(value) {
        if (value === this.active) {
            return;
        }
        this.active = value;
        if (value) {
            this.fetch();
        } else {
            // Nothing is watching. Dropping the numbers keeps a stale badge
            // from being the first thing seen on the way back in, before the
            // fresh count lands.
            this.counters.unassigned = 0;
            this.counters.mine = 0;
        }
    }
}

services.add(OmniMenuCountersPlugin);
