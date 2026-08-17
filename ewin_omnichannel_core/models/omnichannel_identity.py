from odoo import api, fields, models


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
    handle = fields.Char(
        compute="_compute_handle",
        help="How this person is addressed on their channel: the email "
             "address, the @username, the phone number, or the raw external "
             "id — whichever the channel gives us. Shown next to the customer "
             "so an operator can tell two same-named people apart.")
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

    @api.depends("email", "username", "phone", "external_id")
    def _compute_handle(self):
        """Pick the most recognisable identifier the channel gave us. The
        external id is last because it is the only one always present, and on
        chat channels it is an opaque number nobody recognises — on email it
        happens to be the address itself, which is why identities imported
        before the email field existed still read correctly."""
        for identity in self:
            identity.handle = (
                identity.email
                or (identity.username and f"@{identity.username}")
                or identity.phone
                or identity.external_id)
