from odoo import api, fields, models
from odoo.exceptions import ValidationError


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

    # Uniqueness is enforced in Python, not with a `unique(name, company_id)`
    # SQL constraint, for two reasons that a plain SQL index cannot handle:
    # 1. NULL semantics — Postgres treats NULL as distinct from NULL, so a
    #    SQL unique constraint never fires for two *shared* reasons
    #    (company_id empty on both), which is the common case since all the
    #    shipped defaults are shared. Comparing company_id as a Python value
    #    below makes False collide with False the way an administrator
    #    expects.
    # 2. jsonb storage — `name` is translate=True, so its column holds a
    #    per-language jsonb map, not plain text. A SQL uniqueness check
    #    would compare that map structurally, so two rows whose *displayed*
    #    text is identical could still dodge it if their language keys
    #    differ. Reading `reason.name` below compares the active language's
    #    label instead.
    @api.constrains("name", "company_id")
    def _check_name_unique_per_company(self):
        for reason in self:
            domain = [
                ("id", "!=", reason.id),
                ("name", "=", reason.name),
                ("company_id", "=", reason.company_id.id),
            ]
            if self.search_count(domain):
                raise ValidationError(
                    "Close reason must be unique per company.")
