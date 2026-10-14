/** @odoo-module **/

import { Component, markup, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * What the channel sends under the reply by itself — for email, the
 * conversation so far, quoted — folded behind a "•••" button the way a mail
 * client folds a quote. The reply is what the operator is writing; the quote
 * is there to be checked, not read every time, so it starts closed.
 */
export class OmniQuotePreviewField extends Component {
    static template = "ewin_omnichannel_core.OmniQuotePreviewField";
    static props = { ...standardFieldProps };

    setup() {
        this.state = useState({ open: false });
    }

    get html() {
        // Built on the server from sanitized message bodies, with every
        // added word escaped there; the field itself is not re-sanitized.
        return markup(this.props.record.data[this.props.name] || "");
    }

    toggle() {
        this.state.open = !this.state.open;
    }
}

export const omniQuotePreviewField = {
    component: OmniQuotePreviewField,
    supportedTypes: ["html"],
};

registry.category("fields").add("omni_quote_preview", omniQuotePreviewField);
