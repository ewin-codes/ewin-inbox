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
        # Grouped rather than len(omni_conversation_ids): one query whatever
        # the size of self, and no conversation rows read into memory just to
        # be counted.
        groups = self.env["omnichannel.conversation"]._read_group(
            [("lead_id", "in", self.ids)], ["lead_id"], ["__count"])
        counts = {lead.id: count for lead, count in groups}
        for lead in self:
            lead.omni_conversation_count = counts.get(lead.id, 0)

    def _merge_dependences(self, opportunities):
        """Carry the conversation links onto the surviving lead.

        A merge moves every ``mail.message`` of the merged-away leads onto
        ``self`` and then deletes them, at which point ``ondelete="set null"``
        clears ``lead_id`` in the database — behind the ORM, so core's write
        hook never runs and nothing ever purges. Without this, an ordinary
        pipeline merge would leave the conversation linked to no lead while
        its texts sit on the survivor with nothing pointing at them, and no
        UI path left to remove them.

        Re-pointing after ``super`` is what makes it a no-op rather than a
        rewrite: the copies already live on ``self``, so the write's purge for
        the dead lead matches nothing and its backfill finds every message
        already copied.
        """
        result = super()._merge_dependences(opportunities)
        # sudo, like Odoo's own _merge_dependences_history: whoever works the
        # pipeline is not necessarily an Inbox operator, and a merge that left
        # links dangling because the salesperson cannot read conversations
        # would be worse than one that repairs them.
        self.env["omnichannel.conversation"].sudo().search(
            [("lead_id", "in", opportunities.ids)]).write({"lead_id": self.id})
        return result

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
