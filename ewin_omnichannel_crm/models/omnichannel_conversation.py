from odoo import _, api, fields, models
from odoo.exceptions import UserError


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

    def action_create_lead(self):
        """Open a lead seeded from this conversation, already linked to it.

        Refuses when a lead is already linked: quietly creating a second one
        would split a single customer's history across two records and leave
        the first looking abandoned. Re-pointing an existing link is the Lead
        field's job.
        """
        self.ensure_one()
        if self.lead_id:
            raise UserError(_(
                "This conversation is already linked to the lead \"%s\". "
                "Change the Lead field to point it somewhere else.",
                self.lead_id.name))
        lead = self.env["crm.lead"].create(self._prepare_lead_values())
        self.lead_id = lead
        return {
            "type": "ir.actions.act_window",
            "name": _("Lead"),
            "res_model": "crm.lead",
            "res_id": lead.id,
            "view_mode": "form",
        }

    def _prepare_lead_values(self):
        """Seed a lead from what the channel already knows about the customer.

        ``type`` is deliberately absent: ``crm.lead`` computes it from whether
        the user has the Leads feature enabled, and forcing "lead" on an
        installation that works straight in opportunities would create a
        record its own pipeline never shows.
        """
        self.ensure_one()
        identity = self.identity_id
        partner = self.partner_id
        return {
            "name": self.subject or _(
                "%(channel)s conversation with %(customer)s",
                channel=self.channel_id.name or _("Chat"),
                customer=partner.display_name or identity.display_name
                or self.name),
            "partner_id": partner.id or False,
            # contact_name is the free-text stand-in crm.lead uses while no
            # contact exists; filling both would show the customer twice.
            "contact_name": False if partner else (
                identity.display_name or False),
            "email_from": identity.email or partner.email or False,
            "phone": identity.phone or partner.phone or False,
            "user_id": self.operator_id.id or self.env.uid,
        }
