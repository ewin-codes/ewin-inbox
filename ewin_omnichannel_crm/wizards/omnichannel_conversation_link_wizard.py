from odoo import fields, models


class OmnichannelConversationLinkWizard(models.TransientModel):
    _inherit = "omnichannel.conversation.link.wizard"

    lead_id = fields.Many2one(
        "crm.lead", string="Lead", ondelete="cascade")
    lead_partner_id = fields.Many2one(
        related="lead_id.partner_id", string="Lead Contact", readonly=True,
        help="Drives the picker's default filter, so the conversations of the "
             "lead's own contact come up first.")

    def _link_values(self):
        """Attach to the lead when the lead picker opened this wizard.

        Both links live on one wizard now, and writing both would make the
        lead picker quietly re-point the conversation's contact as well — a
        second, invisible effect of pressing Link.
        """
        self.ensure_one()
        if self.lead_id:
            return {"lead_id": self.lead_id.id}
        return super()._link_values()
