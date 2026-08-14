/** @odoo-module **/

import { Component, useRef, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Reply textarea that sends on the configured keyboard shortcut
 * (Enter or Ctrl+Enter, from EWIN Inbox settings). The Send button still works
 * for mouse users. The textarea value is set imperatively so keystrokes never
 * trigger a re-render (no cursor jumps); external changes — cleared after
 * send, filled by a quick reply — are synced back through an effect.
 */
export class OmniComposerField extends Component {
    static template = "ewin_omnichannel_core.OmniComposerField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.textareaRef = useRef("textarea");
        useEffect(
            () => {
                const el = this.textareaRef.el;
                if (el && el.value !== this.value) {
                    el.value = this.value;
                }
            },
            () => [this.value]
        );
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get shortcut() {
        return this.props.record.data.send_shortcut || "ctrl_enter";
    }

    onInput(ev) {
        this.props.record.update({ [this.props.name]: ev.target.value });
    }

    onKeydown(ev) {
        if (ev.key !== "Enter" || ev.isComposing) {
            return;
        }
        const withCtrl = ev.ctrlKey || ev.metaKey;
        const shouldSend =
            this.shortcut === "ctrl_enter" ? withCtrl : !ev.shiftKey && !withCtrl;
        if (!shouldSend) {
            return;
        }
        ev.preventDefault();
        this.send();
    }

    async send() {
        const record = this.props.record;
        const resId = record.resId;
        if (!resId) {
            return;
        }
        // The shortcut does what the primary button says it does — Send,
        // Schedule or Reschedule, whichever is on screen. A hidden second
        // meaning for the same key is how a deferred reply goes out hours
        // early.
        const deferred =
            record.data.composer_editing_message_id ||
            record.data.composer_scheduled_at;
        const method = deferred ? "action_schedule_reply" : "action_send_reply";
        await record.save();
        await this.orm.call("omnichannel.conversation", method, [[resId]]);
        await record.load();
    }
}

export const omniComposerField = {
    component: OmniComposerField,
    supportedTypes: ["text"],
    extractProps: ({ attrs }) => ({ placeholder: attrs.placeholder }),
};

registry.category("fields").add("omni_composer", omniComposerField);
