from odoo import fields, models


class OmnichannelTag(models.Model):
    _name = "omnichannel.tag"
    _description = "Omnichannel Tag"
    _order = "name"

    name = fields.Char(required=True)
    color = fields.Integer()
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True)

    _sql_constraints = [
        ("name_uniq", "unique(name, company_id)", "Tag name must be unique per company."),
    ]
