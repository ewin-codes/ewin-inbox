from odoo import api, fields, models


class OmnichannelConversation(models.Model):
    _inherit = "omnichannel.conversation"

    lead_id = fields.Many2one(
        "crm.lead", string="Lead", index=True, copy=False,
        ondelete="set null",
        help="The CRM lead this conversation belongs to. One lead carries as "
             "many conversations as the customer starts; a conversation "
             "belongs to at most one lead.")

    @api.model
    def _history_link_fields(self):
        return super()._history_link_fields() + ["lead_id"]

    def _history_targets(self):
        # A lead is deleted freely by whoever works the pipeline, and
        # ondelete="set null" then clears the link. Filtering on truthiness
        # here is what keeps a stale write from mirroring into nothing.
        return super()._history_targets() + [
            record for record in (self.lead_id,) if record]
