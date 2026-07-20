from odoo import fields, models


class OmnichannelIdentity(models.Model):
    _name = "omnichannel.identity"
    _description = "Omnichannel External Identity"
    _order = "last_seen_at desc"

    account_id = fields.Many2one(
        "omnichannel.account", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(
        related="account_id.company_id", store=True, index=True)
    external_id = fields.Char(required=True, index=True)
    partner_id = fields.Many2one("res.partner", index=True)
    display_name = fields.Char()
    username = fields.Char()
    phone = fields.Char()
    email = fields.Char()
    avatar_attachment_id = fields.Many2one("ir.attachment")
    language_code = fields.Char()
    raw_metadata = fields.Json(default=dict)
    first_seen_at = fields.Datetime(default=fields.Datetime.now)
    last_seen_at = fields.Datetime(default=fields.Datetime.now)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("account_external_uniq", "unique(account_id, external_id)",
         "An identity with this external id already exists for this account."),
    ]
