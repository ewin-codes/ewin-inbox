from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    omni_source = fields.Char(string="Omnichannel Source")
    omni_external_id = fields.Char(string="External ID", index=True)
    omni_username = fields.Char(string="External Username")
    omni_first_contact = fields.Datetime(string="First Contact")
    omni_identity_ids = fields.One2many(
        "omnichannel.identity", "partner_id", string="External Identities")
    omni_conversation_ids = fields.One2many(
        "omnichannel.conversation", "partner_id", string="Conversations")
    # No string: the only place this renders is the stat button in
    # res_partner_views.xml, which sets its own label — a second
    # "Conversations" here only collides with omni_conversation_ids's.
    omni_conversation_count = fields.Integer(
        compute="_compute_omni_conversation_count")

    @api.depends("omni_conversation_ids")
    def _compute_omni_conversation_count(self):
        # Grouped rather than len(omni_conversation_ids): one query whatever
        # the size of self, and no conversation rows read into memory just to
        # be counted.
        groups = self.env["omnichannel.conversation"]._read_group(
            [("partner_id", "in", self.ids)], ["partner_id"], ["__count"])
        counts = {partner.id: count for partner, count in groups}
        for partner in self:
            partner.omni_conversation_count = counts.get(partner.id, 0)

    def action_omni_conversations(self):
        """Open this contact's conversations from the smart button."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Conversations"),
            "res_model": "omnichannel.conversation",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id},
        }
