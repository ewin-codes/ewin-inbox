from odoo import fields, models


class OmnichannelCloseReason(models.Model):
    _name = "omnichannel.close.reason"
    _description = "Omnichannel Close Reason"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(
        default=10,
        help="Order the reasons appear in when an operator closes a "
             "conversation. Put the everyday ones first.")
    active = fields.Boolean(
        default=True,
        help="Archive a reason instead of deleting it: conversations already "
             "closed with it keep pointing at it.")
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True,
        help="Leave empty to offer this reason to every company.")

    _sql_constraints = [
        ("name_uniq", "unique(name, company_id)",
         "Close reason must be unique per company."),
    ]

    def init(self):
        # unique(name, company_id) above only fires when company_id is set:
        # SQL treats NULL as distinct from NULL, so two shared reasons
        # (company_id empty on both) would otherwise collide silently. This
        # partial index closes that gap for the shared, no-company reasons.
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            omnichannel_close_reason_name_global_uniq
            ON omnichannel_close_reason (name) WHERE company_id IS NULL
        """)
