/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { NavBar } from "@web/webclient/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { useEffect, useState } from "@odoo/owl";

const APP_XMLID = "ewin_omnichannel_core.menu_omnichannel_root";

// Which menu wears which number, and what its colour says. Grey is the queue
// nobody has taken — work for whoever is free. Red is addressed to the reader
// personally, which is the one worth leaving another app for.
const BADGES = {
    "ewin_omnichannel_core.menu_omni_inbox": {
        key: "unassigned",
        className: "text-bg-secondary",
        title: _t("New messages in conversations nobody has taken"),
    },
    "ewin_omnichannel_core.menu_omni_my": {
        key: "mine",
        className: "text-bg-danger",
        title: _t("Unread messages in the conversations assigned to you"),
    },
};

patch(NavBar.prototype, {
    setup() {
        super.setup();
        this.omniMenuCounters = useService("omni_menu_counters");
        this.omniCounters = useState(this.omniMenuCounters.counters);
        useEffect(
            () => {
                this.omniMenuCounters.setActive(this.currentApp?.xmlid === APP_XMLID);
            },
            () => [this.currentApp?.xmlid]
        );
        // A badge widens its section, and the navbar decides what falls into
        // the "More" dropdown by measuring those widths — once per menu or
        // systray change, which a count arriving over the bus is not.
        useEffect(
            () => {
                this.adapt();
            },
            () => [this.omniCounters.unassigned, this.omniCounters.mine]
        );
    },

    /**
     * The badge a navbar section wears, or null for the sections that wear
     * none — which is every section of every other app, and ours while the
     * count is zero.
     */
    omniMenuBadge(section) {
        const badge = BADGES[section.xmlid];
        if (!badge) {
            return null;
        }
        const count = this.omniCounters[badge.key];
        return count ? { ...badge, count } : null;
    },
});
