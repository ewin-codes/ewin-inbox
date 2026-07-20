from odoo import api, fields, models

ERROR_CATEGORIES = [
    ("configuration", "Configuration"), ("authentication", "Authentication"),
    ("validation", "Validation"), ("rate_limit", "Rate Limit"),
    ("network", "Network"), ("provider", "Provider"),
    ("attachment", "Attachment"), ("permission", "Permission"),
    ("internal", "Internal"),
]


class OmnichannelErrorLog(models.Model):
    _name = "omnichannel.error.log"
    _description = "Omnichannel Error Log"
    _order = "id desc"

    create_date = fields.Datetime(string="Date", readonly=True)
    account_id = fields.Many2one("omnichannel.account", ondelete="cascade", index=True)
    channel_id = fields.Many2one("omnichannel.channel")
    conversation_id = fields.Many2one("omnichannel.conversation", ondelete="set null")
    message_id = fields.Many2one("omnichannel.message", ondelete="set null")
    event_id = fields.Many2one("omnichannel.event", ondelete="set null")
    company_id = fields.Many2one("res.company", index=True)
    category = fields.Selection(ERROR_CATEGORIES, required=True, index=True)
    code = fields.Char()
    summary = fields.Char(required=True)
    technical = fields.Text(groups="ewin_omnichannel_core.group_omni_manager")
    payload = fields.Json(groups="ewin_omnichannel_core.group_omni_admin")
    state = fields.Selection(
        [("new", "New"), ("acknowledged", "Acknowledged"), ("resolved", "Resolved")],
        default="new", index=True)
    responsible_id = fields.Many2one("res.users")
    retry_count = fields.Integer(default=0)

    @api.model
    def log(self, category, summary, code=False, account=None, **ctx):
        vals = {"category": category, "summary": summary, "code": code}
        if account is not None:
            vals["account_id"] = account.id
            vals["channel_id"] = account.channel_id.id
            vals["company_id"] = account.company_id.id
        for key in ("conversation_id", "message_id", "event_id", "technical", "payload"):
            if key in ctx:
                vals[key] = ctx[key]
        return self.create(vals)
