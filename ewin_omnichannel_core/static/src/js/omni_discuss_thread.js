import { Component, onWillDestroy, onWillStart, signal, useOnChange, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Thread } from "@mail/core/common/thread";

/**
 * Odoo's Thread with the per-message actions off. Replying, reacting and
 * editing belong to the composer below and to the channel the reply goes out
 * on; a reaction left on the mirror would reach nobody.
 */
export class OmniThread extends Thread {
    static template = "ewin_omnichannel_core.Thread";
}

/**
 * Read-only chat view of a conversation's mirror discuss.channel, rendered with
 * Odoo's native Thread component: realtime updates over the bus, auto-scroll to
 * the latest message, native attachment previews and avatars.
 */
export class OmniDiscussThreadField extends Component {
    static template = "ewin_omnichannel_core.OmniDiscussThreadField";
    static components = { Thread: OmniThread };

    props = useProps(standardFieldProps);
    thread = signal(undefined);
    /** Bumped to send the Thread to the newest message. */
    jumpPresent = signal(0);

    setup() {
        this.store = useService("mail.store");
        this.orm = useService("orm");
        this.busService = useService("bus_service");
        onWillStart(() => this._loadThread(this.channelId));
        useOnChange(
            () => [this.channelId],
            (channelId) => this._loadThread(channelId),
            { initialRun: false }
        );
        // Realtime: the server pushes "omni.inbox" to the operator's own bus
        // channel on every new message in their conversations. Refetch when the
        // event is for the conversation currently shown, so replies and inbound
        // messages appear without a manual reload (a freshly-assigned mirror
        // channel is not yet live on the client's bus until the next reload).
        onWillDestroy(
            this.busService.subscribe("omni.inbox", (payload) => {
                if (payload?.conversation_id !== this.props.record.resId) {
                    return;
                }
                // A scheduled reply is deliberately NOT in the thread yet, so a
                // refetch would find nothing and only jerk every open copy of
                // this conversation down to the newest message.
                if (payload.event === "message_scheduled") {
                    return;
                }
                this._refreshMessages();
            })
        );
    }

    get channelId() {
        const value = this.props.record.data[this.props.name];
        if (!value) {
            return false;
        }
        if (Array.isArray(value)) {
            return value[0] || false;
        }
        return value.id || false;
    }

    _jumpToPresent() {
        this.jumpPresent.set(this.jumpPresent() + 1);
    }

    async _refreshMessages() {
        const thread = this.thread();
        if (!thread) {
            return;
        }
        try {
            await thread.fetchNewMessages();
            this._jumpToPresent();
        } catch {
            // transient/access errors: keep the current view as-is
        }
    }

    async _loadThread(channelId) {
        if (!channelId) {
            this.thread.set(undefined);
            return;
        }
        if (this.thread()?.id === channelId) {
            return;
        }
        const thread = this.store["mail.thread"].insert({
            model: "discuss.channel",
            id: channelId,
        });
        this.thread.set(thread);
        try {
            await thread.fetchNewMessages();
        } catch {
            // transient/access errors: the (possibly empty) thread still renders
        }
        // Open on the latest message (order "asc" -> newest at the bottom).
        this._jumpToPresent();
        // Opening the conversation counts as reading it: clear the list badge.
        const resId = this.props.record.resId;
        if (resId) {
            this.orm
                .call("omnichannel.conversation", "action_seen", [[resId]])
                .catch(() => {});
        }
    }
}

export const omniDiscussThreadField = {
    component: OmniDiscussThreadField,
    supportedTypes: ["many2one"],
};

registry.category("fields").add("omni_discuss_thread", omniDiscussThreadField);
