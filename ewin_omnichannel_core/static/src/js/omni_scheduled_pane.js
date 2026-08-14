/** @odoo-module **/

import { Component, useEffect, useState, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { deserializeDateTime, formatDate } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";

/**
 * The waiting replies of a conversation, drawn as the chat they will become.
 *
 * A tab strip — "Chat" | "Scheduled <n>" — sits above the thread and swaps it
 * for this pane. The strip renders only while replies are waiting, so an
 * ordinary conversation pays no screen space for the feature. Which tab is
 * active is view state of one operator rather than data (two operators share a
 * conversation record), so it lives here, and the thread is hidden through a
 * sibling selector on `.o-scheduled-on` rather than an `invisible` modifier —
 * which could only read fields of the record.
 *
 * Each reply is a bubble with the avatar and name of whoever scheduled it and
 * the time it is due, and carries the three things that can still be done to
 * it: edit, send now, cancel. Editing loads the reply back into the composer
 * below, so a deferred reply is changed with the same textarea, quick replies
 * and send-later control it was written with.
 *
 * The rows are read straight from the server rather than through the form's
 * one2many. A one2many is a datapoint of the record, refreshable only by
 * reloading the whole record — which would throw away whatever is half-typed
 * in the composer. Reading them here makes a refresh a plain re-read, which is
 * what lets the bus keep this pane honest the moment the cron releases a reply.
 */
export class OmniScheduledPaneField extends Component {
    static template = "ewin_omnichannel_core.OmniScheduledPaneField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.busService = useService("bus_service");
        this._seenCount = this.recordCount;
        this._seenPending = this.recordPending;
        this._seenBody = this.recordBody;
        this.state = useState({
            count: this._seenCount,
            scheduledTab: false,
            messages: [],
        });
        // The strip needs a count, which the record already carries — so
        // nothing is fetched until the pane is actually opened or the count
        // changes under it.
        useEffect(
            (count, pending, body) =>
                this._onRecordRefreshed(count, pending, body),
            () => [this.recordCount, this.recordPending, this.recordBody]
        );
        // Realtime: the same "omni.inbox" signal the thread listens to. A
        // reply the cron has just released must leave this pane on its own, or
        // the operator keeps looking at a reply that already went out.
        this._onOmniEvent = (payload) => {
            if (!payload || payload.conversation_id !== this.props.record.resId) {
                return;
            }
            this._load();
        };
        this.busService.subscribe("omni.inbox", this._onOmniEvent);
        onWillUnmount(() =>
            this.busService.unsubscribe("omni.inbox", this._onOmniEvent)
        );
    }

    get recordCount() {
        return this.props.record.data[this.props.name] || 0;
    }

    /**
     * True while the composer holds a moment to send at — the state that turns
     * into one more waiting reply when Schedule is pressed.
     */
    get recordPending() {
        return Boolean(this.props.record.data.composer_scheduled_at);
    }

    /** What is currently in the composer, as the record holds it. */
    get recordBody() {
        return this.props.record.data.composer_body || "";
    }

    /** The waiting replies, split into the days they are due on. */
    get days() {
        const days = [];
        for (const message of this.state.messages) {
            const when = deserializeDateTime(message.scheduled_at);
            const day = formatDate(when);
            const bubble = { ...message, time: when.toFormat("HH:mm") };
            const current = days[days.length - 1];
            if (current && current.day === day) {
                current.messages.push(bubble);
            } else {
                days.push({ day, messages: [bubble] });
            }
        }
        return days;
    }

    avatarUrl(message) {
        return `/web/image/res.users/${message.author_id}/avatar_128`;
    }

    _onRecordRefreshed(count, pending, body) {
        // Posting empties the composer: the text goes and, when the reply was
        // deferred, the moment to send it goes with it. Both at once is the
        // fingerprint of *this* operator having just pressed Schedule, so the
        // pane opens on it. Neither half alone would do — clearing the picker
        // by hand also drops the moment, and an ordinary Send also empties the
        // text — and the count cannot stand in for either, because a reply
        // released or cancelled since the last read leaves the record's own
        // count behind the truth.
        const posted = Boolean(this._seenBody) && !body;
        const scheduleFired = this._seenPending && !pending && posted;
        const changed = count !== this._seenCount;
        this._seenCount = count;
        this._seenPending = pending;
        this._seenBody = body;
        // The record is the fresher source only in the moment it changes.
        // Between reloads this pane's own reads run ahead of it, and taking
        // its count on every keystroke would put a released reply back on the
        // strip the moment the operator starts typing.
        if (changed) {
            this.state.count = count;
            if (!count) {
                this.state.scheduledTab = false;
                this.state.messages = [];
                return;
            }
        }
        if (scheduleFired) {
            this.state.scheduledTab = true;
        }
        if (changed || scheduleFired) {
            this._load();
        }
    }

    async _load() {
        const resId = this.props.record.resId;
        if (!resId) {
            return;
        }
        let messages;
        try {
            messages = await this.orm.call(
                "omnichannel.conversation", "scheduled_replies", [[resId]]);
        } catch {
            return; // transient/access errors: keep showing what we have
        }
        this.state.messages = messages;
        this.state.count = messages.length;
        if (!messages.length) {
            this.state.scheduledTab = false;
        }
    }

    async showScheduled(scheduled) {
        this.state.scheduledTab = scheduled;
        if (scheduled) {
            await this._load();
        }
    }

    /**
     * Hand a reply back to the composer.
     *
     * The record is reloaded because the composer fields are the record's:
     * the server has just written the reply's text and time into them, and
     * only a reload brings them to the screen. Whatever was half-typed is
     * deliberately replaced — asking to edit a reply is asking for exactly
     * that.
     */
    async editReply(message) {
        const record = this.props.record;
        try {
            await this.orm.call(
                "omnichannel.conversation", "action_edit_scheduled",
                [[record.resId], message.id]);
        } finally {
            // Also on failure: the reply is gone from under the operator, and
            // the pane should stop showing it.
            await this._load();
        }
        await record.load();
    }

    async sendNow(message) {
        await this._act("omnichannel.message", "action_send_now", message);
    }

    cancelReply(message) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Cancel this reply?"),
            body: _t(
                "It will not be sent. The reply stays in the conversation's " +
                "history, marked cancelled."),
            confirmLabel: _t("Cancel the reply"),
            confirmClass: "btn-danger",
            cancelLabel: _t("Keep it"),
            confirm: () => this._act(
                "omnichannel.message", "action_cancel_schedule", message),
            // Without a cancel callback the dialog renders no way back but the
            // cross — one click from dropping a reply by accident.
            cancel: () => {},
        });
    }

    async _act(model, method, message) {
        try {
            await this.orm.call(model, method, [[message.id]]);
        } finally {
            await this._load();
            await this._closeEditorFor(message);
        }
    }

    /**
     * Stop editing a reply that has just left.
     *
     * The server has already dropped the link — a reply that is gone cannot
     * stay open in anyone's composer — but the form holds its own copy of that
     * field, and until it hears otherwise it goes on showing an edit banner
     * for a reply nobody can save. Only the link is cleared, not the text: the
     * words are the operator's, and Reschedule will make a new reply of them.
     */
    async _closeEditorFor(message) {
        const record = this.props.record;
        const editing = record.data.composer_editing_message_id;
        const editingId = Array.isArray(editing)
            ? editing[0]
            : (editing && editing.id) || false;
        if (editingId === message.id) {
            await record.update({ composer_editing_message_id: false });
        }
    }
}

export const omniScheduledPaneField = {
    component: OmniScheduledPaneField,
    supportedTypes: ["integer"],
};

registry.category("fields").add("omni_scheduled_pane", omniScheduledPaneField);
