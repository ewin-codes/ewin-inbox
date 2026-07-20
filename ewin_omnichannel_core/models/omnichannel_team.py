from odoo import fields, models


class OmnichannelTeam(models.Model):
    _name = "omnichannel.team"
    _description = "Omnichannel Operator Team"
    _order = "name"

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    user_ids = fields.Many2many("res.users", string="Operators")
    manager_id = fields.Many2one("res.users", string="Manager")
    active = fields.Boolean(default=True)
