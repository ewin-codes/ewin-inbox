from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    omni_source = fields.Char(string="Omnichannel Source")
    omni_external_id = fields.Char(string="External ID", index=True)
    omni_username = fields.Char(string="External Username")
    omni_first_contact = fields.Datetime(string="First Contact")
    omni_identity_ids = fields.One2many(
        "omnichannel.identity", "partner_id", string="External Identities")
