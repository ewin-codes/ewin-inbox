/** @odoo-module **/

import { Component, useRef, useEffect, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Reply textarea that sends on the configured keyboard shortcut
 * (Enter or Ctrl+Enter, from EWIN Inbox settings). The Send button still works
 * for mouse users. The textarea value is set imperatively so keystrokes never
 * trigger a re-render (no cursor jumps); external changes (cleared after send)
 * are synced back through an effect.
 *
 * A "Quick replies" dropdown lists the operator's templates and inserts the
 * chosen one (with {{name}} filled from the customer) into the textarea.
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
        this.state = useState({ open: false, templates: [] });
        onWillStart(() => this.loadTemplates());
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

    get channelId() {
        const v = this.props.record.data.channel_id;
        if (Array.isArray(v)) {
            return v[0];
        }
        return (v && v.id) || false;
    }

    async loadTemplates() {
        // global templates (no channel) + those scoped to this conversation's channel
        const ch = this.channelId;
        const domain = ch
            ? ["|", ["channel_id", "=", false], ["channel_id", "=", ch]]
            : [["channel_id", "=", false]];
        this.state.templates = await this.orm.searchRead(
            "omnichannel.template",
            domain,
            ["id", "name", "shortcut"]
        );
    }

    toggleMenu() {
        this.state.open = !this.state.open;
    }

    async insertTemplate(template) {
        this.state.open = false;
        const resId = this.props.record.resId;
        const rendered = await this.orm.call(
            "omnichannel.template",
            "render_for_conversation",
            [template.id, resId]
        );
        const current = this.value;
        const next = current ? `${current}\n${rendered}` : rendered;
        await this.props.record.update({ [this.props.name]: next });
        const el = this.textareaRef.el;
        if (el) {
            el.value = next;
            el.focus();
        }
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
        // While a scheduled reply is loaded, the shortcut does what the button
        // under the textarea says it does: it applies the edit. Sending a
        // reply that is already written and waiting is not what the operator
        // reaches for Enter to do, and a hidden second meaning for the same
        // key is how a deferred reply goes out three hours early.
        const method = record.data.composer_editing_message_id
            ? "action_schedule_reply"
            : "action_send_reply";
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
