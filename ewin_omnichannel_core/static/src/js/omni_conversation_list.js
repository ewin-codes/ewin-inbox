import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { onWillDestroy } from "@odoo/owl";

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
        const unsubscribe = [
            bus.subscribe("discuss.channel/new_message", reload),
            // Also reload on our own realtime signal, which reaches the
            // operator even when a just-assigned mirror channel is not yet
            // live on the bus.
            bus.subscribe("omni.inbox", reload),
        ];
        onWillDestroy(() => {
            clearTimeout(timer);
            unsubscribe.forEach((off) => off());
        });
    }
}

registry.category("views").add("omni_conversation_list", {
    ...listView,
    Controller: OmniConversationListController,
});
