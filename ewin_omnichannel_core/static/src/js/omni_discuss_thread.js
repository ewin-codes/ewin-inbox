/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Thread } from "@mail/core/common/thread";

/**
 * Read-only chat view of a conversation's mirror discuss.channel, rendered with
 * Odoo's native Thread component: realtime updates over the bus, auto-scroll to
 * the latest message, native attachment previews and avatars. Replying happens
 * through the dedicated Telegram composer below, so per-message actions are off.
 */
export class OmniDiscussThreadField extends Component {
    static template = "ewin_omnichannel_core.OmniDiscussThreadField";
    static components = { Thread };
    static props = { ...standardFieldProps };

    setup() {
        this.store = useState(useService("mail.store"));
        this.orm = useService("orm");
        this.state = useState({ thread: undefined, jumpPresent: 0 });
        onWillStart(() => this._loadThread(this.props));
        onWillUpdateProps((nextProps) => this._loadThread(nextProps));
    }

    _channelId(props) {
        const value = props.record.data[props.name];
        if (!value) {
            return false;
        }
        if (Array.isArray(value)) {
            return value[0] || false;
        }
        return value.id || false;
    }

    async _loadThread(props) {
        const channelId = this._channelId(props);
        if (!channelId) {
            this.state.thread = undefined;
            return;
        }
        if (this.state.thread && this.state.thread.id === channelId) {
            return;
        }
        const thread = this.store.Thread.insert({
            model: "discuss.channel",
            id: channelId,
        });
        this.state.thread = thread;
        try {
            await thread.fetchNewMessages();
        } catch {
            // transient/access errors: the (possibly empty) thread still renders
        }
        // bump jumpPresent so the Thread scrolls to the latest message on open
        // (order "asc" -> newest at the bottom)
        this.state.jumpPresent++;
        // Opening the conversation counts as reading it: clear the list badge.
        const resId = props.record.resId;
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
