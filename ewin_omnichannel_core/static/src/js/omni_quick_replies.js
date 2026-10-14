/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { insertIntoReply, signatureBlock } from "./omni_signature";

/**
 * "Quick replies": the operator's canned templates, listed for the channel the
 * conversation is on and inserted into the composer below.
 *
 * It lives in the composer's header rather than inside the composer widget, so
 * that the heading, the internal-note switch and this button share the single
 * line above the textarea instead of stacking two rows of furniture on top of
 * it.
 *
 * Bound to `channel_id` — the field that decides which templates apply — and
 * it writes what it renders into `composer_body`, which the composer picks up
 * through the sync effect it already runs for every external change.
 */
export class OmniQuickRepliesField extends Component {
    static template = "ewin_omnichannel_core.OmniQuickRepliesField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ open: false, templates: [] });
        onWillStart(() => this.loadTemplates());
    }

    get channelId() {
        const value = this.props.record.data[this.props.name];
        if (Array.isArray(value)) {
            return value[0] || false;
        }
        return (value && value.id) || false;
    }

    async loadTemplates() {
        // global templates (no channel) + those scoped to this conversation's
        // channel
        const channel = this.channelId;
        const domain = channel
            ? ["|", ["channel_id", "=", false], ["channel_id", "=", channel]]
            : [["channel_id", "=", false]];
        this.state.templates = await this.orm.searchRead(
            "omnichannel.template", domain, ["id", "name", "shortcut"]);
    }

    toggleMenu() {
        this.state.open = !this.state.open;
    }

    async insertTemplate(template) {
        this.state.open = false;
        const record = this.props.record;
        const rendered = await this.orm.call(
            "omnichannel.template", "render_for_conversation",
            [template.id, record.resId]);
        // An untouched composer holds the signature on screen only, not in
        // the record: start from what the operator sees, so the reply lands
        // above the signature rather than replacing it.
        const block = signatureBlock(record.data);
        const current = record.data.composer_body || block;
        await record.update({
            composer_body: insertIntoReply(current, block, rendered),
        });
        // Inserting a template is the start of writing a reply, not the end of
        // one: put the caret where the operator will keep typing. The textarea
        // belongs to the composer widget, which owns its own DOM — this reaches
        // across for the focus alone, and reads nothing.
        document.querySelector(".o_omni_composer_input")?.focus();
    }
}

export const omniQuickRepliesField = {
    component: OmniQuickRepliesField,
    supportedTypes: ["many2one"],
};

registry.category("fields").add("omni_quick_replies", omniQuickRepliesField);
