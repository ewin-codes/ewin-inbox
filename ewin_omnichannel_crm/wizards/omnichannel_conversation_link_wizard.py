from odoo import fields, models


class OmnichannelConversationLinkWizard(models.TransientModel):
    _name = "omnichannel.conversation.link.wizard"
    _description = "Link Conversations to a Lead"

    lead_id = fields.Many2one(
        "crm.lead", string="Lead", required=True, ondelete="cascade")
    lead_partner_id = fields.Many2one(
        related="lead_id.partner_id", string="Lead Contact", readonly=True,
        help="Drives the picker's default filter, so the conversations of the "
             "lead's own contact come up first.")
    conversation_ids = fields.Many2many(
        "omnichannel.conversation", "omni_link_wizard_conv_rel",
        "wizard_id", "conversation_id", string="Conversations", required=True)

    def action_confirm(self):
        """Attach the chosen conversations to the lead.

        A plain write, on purpose: it is the conversation's own ``write`` that
        backfills the history, so the wizard and the Lead field on the form
        cannot drift apart.
        """
        self.ensure_one()
        self.conversation_ids.write({"lead_id": self.lead_id.id})
        return {"type": "ir.actions.act_window_close"}
