/** @odoo-module **/

import { Component, useRef, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { replyEnd, signatureBlock } from "./omni_signature";

/**
 * Reply textarea that sends on the configured keyboard shortcut
 * (Enter or Ctrl+Enter, from EWIN Inbox settings). The Send button still works
 * for mouse users. The textarea value is set imperatively so keystrokes never
 * trigger a re-render (no cursor jumps); external changes — cleared after
 * send, filled by a quick reply — are synced back through an effect.
 *
 * A channel that signs its replies (email) has the composer open with the
 * signature below an empty first line, as a mail client does. Until the
 * operator types, the signature is on screen only — the record stays clean,
 * so opening a conversation is not an unsaved change — and a click or a Tab
 * into the composer puts the caret on that first line instead of wherever
 * the pointer landed.
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
        // The last value this widget wrote from a keystroke. The record
        // echoing it back is not an external change: re-showing the signature
        // then would put back what the operator just deleted.
        this.typed = null;
        useEffect(
            () => {
                const el = this.textareaRef.el;
                if (!el || (this.typed !== null && this.value === this.typed)) {
                    return;
                }
                const shown = this.value || this.signature;
                if (el.value !== shown) {
                    el.value = shown;
                    // After a send or a quick reply the next words go right
                    // above the signature, not after it.
                    const end = replyEnd(shown, this.signature);
                    el.setSelectionRange(end, end);
                }
                this.fitHeight();
            },
            () => [this.value, this.signature]
        );
    }

    /**
     * Grow with the text: a signature below the reply is only useful if it
     * is on screen, and a fixed two-row box hid it under a scrollbar. The
     * stylesheet's max-height caps it, and past that the textarea scrolls.
     */
    fitHeight() {
        const el = this.textareaRef.el;
        if (!el) {
            return;
        }
        el.style.height = "auto";
        el.style.height = `${el.scrollHeight + 2}px`;
    }

    get signature() {
        return signatureBlock(this.props.record.data);
    }

    /**
     * Nothing written yet: the composer holds the signature alone, and the
     * caret belongs on the empty line above it.
     */
    placeCaret() {
        const el = this.textareaRef.el;
        const signature = this.signature;
        if (!el || !signature || el.value.slice(0, replyEnd(el.value, signature)).trim()) {
            return;
        }
        el.setSelectionRange(0, 0);
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get shortcut() {
        return this.props.record.data.send_shortcut || "ctrl_enter";
    }

    onInput(ev) {
        this.typed = ev.target.value;
        this.fitHeight();
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
