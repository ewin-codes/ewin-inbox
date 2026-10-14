/** @odoo-module **/

import { Component, markup, useRef, useEffect, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { replyEnd, signatureBlock } from "./omni_signature";

/**
 * Reply box that sends on the configured keyboard shortcut (Enter or
 * Ctrl+Enter, from EWIN Inbox settings). The Send button still works for
 * mouse users. The textarea value is set imperatively so keystrokes never
 * trigger a re-render (no cursor jumps); external changes — cleared after
 * send, filled by a quick reply — are synced back through an effect.
 *
 * A channel that signs its replies (email) has the box open with the
 * signature below an empty first line, as a mail client does. Until the
 * operator types, the signature is on screen only — the record stays clean,
 * so opening a conversation is not an unsaved change — and a click or a Tab
 * into the box puts the caret on that first line instead of wherever the
 * pointer landed.
 *
 * A channel that sends something under the reply by itself (the email quote
 * of the conversation so far) has it folded behind a "•••" at the bottom of
 * the same box, as mail clients fold a quote. Unfolded, it is part of the
 * text — greyed, and editable: what the operator leaves there is what goes
 * out, deleting all of it included. Left untouched it is not stored at all
 * and the channel builds it at send time, so it still takes in whatever the
 * customer writes meanwhile.
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
        this.quoteRef = useRef("quote");
        this.state = useState({ quoteOpen: false });
        // The last value this widget wrote from a keystroke. The record
        // echoing it back is not an external change: re-showing the signature
        // then would put back what the operator just deleted.
        this.typed = null;
        // Same for the quote: once the operator edits it, the editor is the
        // source and must not be overwritten under their caret.
        this.quoteTyped = false;
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
                    if (!this.value) {
                        // A fresh reply starts with its quote folded again.
                        this.state.quoteOpen = false;
                    }
                }
                this.fitHeight();
            },
            () => [this.value, this.signature]
        );
        useEffect(
            (open, edited, quote) => {
                const el = this.quoteRef.el;
                if (!edited) {
                    this.quoteTyped = false;
                }
                if (!open || !el || this.quoteTyped) {
                    return;
                }
                el.innerHTML = quote;
            },
            () => [this.state.quoteOpen, this.quoteEdited, this.quoteHtml]
        );
    }

    get data() {
        return this.props.record.data;
    }

    get value() {
        return this.data[this.props.name] || "";
    }

    get signature() {
        return signatureBlock(this.data);
    }

    get shortcut() {
        return this.data.send_shortcut || "ctrl_enter";
    }

    /** Whether the channel sends anything under this reply by itself. */
    get hasQuote() {
        return !this.data.composer_is_internal
            && Boolean(this.data.composer_quote || this.quoteEdited);
    }

    get quoteEdited() {
        return Boolean(this.data.composer_quote_edited);
    }

    /** The operator's copy once they have changed it, the channel's before. */
    get quoteHtml() {
        const html = this.quoteEdited
            ? this.data.composer_quote_body
            : this.data.composer_quote;
        // Built on the server from sanitized message bodies, every added word
        // escaped there; an edited copy is sanitized again when it is saved.
        return markup(html || "");
    }

    /**
     * Grow with the text: a signature below the reply is only useful if it
     * is on screen. The box around it caps the height and scrolls past that.
     */
    fitHeight() {
        const el = this.textareaRef.el;
        if (!el) {
            return;
        }
        el.style.height = "auto";
        el.style.height = `${el.scrollHeight}px`;
    }

    /**
     * Nothing written yet: the box holds the signature alone, and the caret
     * belongs on the empty line above it.
     */
    placeCaret() {
        const el = this.textareaRef.el;
        const signature = this.signature;
        if (!el || !signature || el.value.slice(0, replyEnd(el.value, signature)).trim()) {
            return;
        }
        el.setSelectionRange(0, 0);
    }

    /** A click on the box's padding is a click into the reply. */
    onBoxClick(ev) {
        if (ev.target === ev.currentTarget) {
            this.textareaRef.el?.focus();
        }
    }

    toggleQuote() {
        this.state.quoteOpen = !this.state.quoteOpen;
    }

    onInput(ev) {
        this.typed = ev.target.value;
        this.fitHeight();
        this.props.record.update({ [this.props.name]: ev.target.value });
    }

    onQuoteInput(ev) {
        this.quoteTyped = true;
        this.props.record.update({
            composer_quote_edited: true,
            composer_quote_body: ev.target.innerHTML,
        });
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
