/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { onWillUnmount } from "@odoo/owl";

// Inbox list is a plain backend list, which Odoo does not refresh in realtime.
// The linked Discuss channels DO push "discuss.channel/new_message" over the
// bus to their members (the assigned operator). We listen for it and reload the
// list (debounced) so the unread badge in the "Customer" cell — a server-side
// computed field — appears without the operator pressing F5.
export class OmniConversationListController extends ListController {
    setup() {
        super.setup();
        const bus = useService("bus_service");
        let timer = null;
        const reload = () => {
            clearTimeout(timer);
            // small debounce: a burst of messages triggers a single reload
            timer = setTimeout(() => this.model.load(), 400);
        };
        this._omniOnNewMessage = () => reload();
        bus.subscribe("discuss.channel/new_message", this._omniOnNewMessage);
        onWillUnmount(() => {
            clearTimeout(timer);
            bus.unsubscribe("discuss.channel/new_message", this._omniOnNewMessage);
        });
    }
}

registry.category("views").add("omni_conversation_list", {
    ...listView,
    Controller: OmniConversationListController,
});
