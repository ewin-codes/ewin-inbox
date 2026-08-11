from odoo import _, api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    omni_conversation_ids = fields.One2many(
        "omnichannel.conversation", "lead_id", string="Conversations")
    # No `string` on the count: two fields of one model sharing a label make
    # Odoo warn on every registry load, and this one is only ever rendered
    # inside the stat button, which sets its own label.
    omni_conversation_count = fields.Integer(
        compute="_compute_omni_conversation_count")

    @api.depends("omni_conversation_ids")
    def _compute_omni_conversation_count(self):
        # Grouped rather than len(omni_conversation_ids): the pipeline kanban
        # computes this for every card on screen.
        groups = self.env["omnichannel.conversation"]._read_group(
            [("lead_id", "in", self.ids)], ["lead_id"], ["__count"])
        counts = {lead.id: count for lead, count in groups}
        for lead in self:
            lead.omni_conversation_count = counts.get(lead.id, 0)

    def action_omni_conversations(self):
        """Open this lead's conversations from the smart button."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Conversations"),
            "res_model": "omnichannel.conversation",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {"default_lead_id": self.id},
        }

    def action_omni_link_conversations(self):
        """Open the picker that attaches existing conversations to this lead."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Link Conversations"),
            "res_model": "omnichannel.conversation.link.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_lead_id": self.id},
        }
