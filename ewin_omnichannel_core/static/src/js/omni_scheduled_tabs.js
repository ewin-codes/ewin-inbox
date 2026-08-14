/** @odoo-module **/

import { Component, useEffect, useState, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Tab strip above the chat: "Chat" | "Scheduled <n>".
 *
 * The strip renders only while replies are waiting, so an ordinary
 * conversation pays no screen space for the feature while a deferred one shows
 * the count without anything being opened. Which tab is active is view state
 * of one operator rather than data — two operators share a conversation record
 * — so it lives here, and the panels it swaps are hidden in CSS through
 * sibling selectors on `.o-scheduled-on`, never through an `invisible`
 * modifier (which can only read fields of the record).
 *
 * Bound to `scheduled_count` because that is the value it displays; the
 * waiting replies themselves are the sibling one2many.
 */
export class OmniScheduledTabsField extends Component {
    static template = "ewin_omnichannel_core.OmniScheduledTabsField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.busService = useService("bus_service");
        this._seenCount = this.recordCount;
        this._seenPending = this.recordPending;
        this.state = useState({ count: this._seenCount, scheduledTab: false });
        // Re-seed from the record only when the record itself changed (a save,
        // a reload, another conversation opened): a plain re-render must not
        // overwrite a fresher count the bus pushed in the meantime.
        useEffect(
            (count, pending) => this._onRecordRefreshed(count, pending),
            () => [this.recordCount, this.recordPending]
        );
        // Realtime: the same "omni.inbox" signal the thread listens to. A
        // reply the cron has just released must empty the strip on its own, or
        // the operator keeps looking at a reply that already left.
        this._onOmniEvent = (payload) => {
            if (!payload || payload.conversation_id !== this.props.record.resId) {
                return;
            }
            this._refreshCount();
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

    _onRecordRefreshed(count, pending) {
        // Scheduling clears the composer's moment and adds a waiting reply in
        // the same round-trip. That pair is the signature of *this* operator
        // pressing Schedule, so the tab opens on it — and not when a
        // colleague's reply lands in the same conversation while this operator
        // is reading the chat.
        const scheduleFired =
            count > this._seenCount && this._seenPending && !pending;
        this._seenCount = count;
        this._seenPending = pending;
        this.state.count = count;
        if (!count) {
            this.state.scheduledTab = false;
        } else if (scheduleFired) {
            this.state.scheduledTab = true;
        }
    }

    async _refreshCount() {
        const resId = this.props.record.resId;
        if (!resId) {
            return;
        }
        let count = 0;
        try {
            const [row] = await this.orm.read(
                "omnichannel.conversation", [resId], ["scheduled_count"]);
            count = row ? row.scheduled_count : 0;
        } catch {
            return; // transient/access errors: keep showing what we have
        }
        if (count === this.state.count) {
            return;
        }
        this.state.count = count;
        if (!count) {
            this.state.scheduledTab = false;
        } else if (this.state.scheduledTab) {
            await this._reload();
        }
    }

    async showScheduled(scheduled) {
        this.state.scheduledTab = scheduled;
        if (scheduled) {
            await this._reload();
        }
    }

    /**
     * Re-read the record so the waiting-replies list drops what already left.
     *
     * That list is a datapoint of this form: the bus can refresh the count but
     * never the rows. Saving first is not optional — the reply being typed
     * lives in the record client-side (omni_composer writes straight into it),
     * and a bare load() would drop it mid-sentence. Persisting it costs
     * nothing: composer_body is stored precisely so a draft survives.
     */
    async _reload() {
        const record = this.props.record;
        if (await record.isDirty()) {
            if (!(await record.save())) {
                return;
            }
        }
        await record.load();
    }
}

export const omniScheduledTabsField = {
    component: OmniScheduledTabsField,
    supportedTypes: ["integer"],
};

registry.category("fields").add("omni_scheduled_tabs", omniScheduledTabsField);
