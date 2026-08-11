from odoo import fields, models


class OmnichannelConversationLinkWizard(models.TransientModel):
    """Attach existing conversations to a customer record.

    The reverse of the link fields on the conversation form: the operator is
    already looking at the customer and wants their conversations gathered
    onto it. Which record that is depends on the module contributing the
    button — core links a contact, the CRM bridge extends this with a lead —
    so the write itself is a hook.
    """

    _name = "omnichannel.conversation.link.wizard"
    _description = "Link Conversations to a Customer Record"

    partner_id = fields.Many2one(
        "res.partner", string="Contact", ondelete="cascade")
    conversation_ids = fields.Many2many(
        "omnichannel.conversation", "omni_link_wizard_conv_rel",
        "wizard_id", "conversation_id", string="Conversations", required=True)

    def _link_values(self):
        """What to write on the chosen conversations. Bridges override."""
        self.ensure_one()
        return {"partner_id": self.partner_id.id}

    def action_confirm(self):
        """Attach the chosen conversations.

        A plain write, on purpose: it is the conversation's own ``write`` that
        backfills the history, so this wizard and the link fields on the
        conversation form cannot drift apart.
        """
        self.ensure_one()
        self.conversation_ids.write(self._link_values())
        return {"type": "ir.actions.act_window_close"}
