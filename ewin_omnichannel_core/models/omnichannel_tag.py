from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OmnichannelTag(models.Model):
    _name = "omnichannel.tag"
    _description = "Omnichannel Tag"
    _order = "name"

    name = fields.Char(required=True)
    color = fields.Integer()
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True,
        help="Leave empty to offer this tag to every company.")

    # Checked in Python rather than with a `unique(name, company_id)` SQL
    # constraint, for the reason omnichannel.close.reason spells out: Postgres
    # treats NULL as distinct from NULL, so the SQL index never fires for two
    # tags shared by every company. The search runs as the current user for
    # the same reason as well — sudo() would turn the error into a probe for
    # tags of companies the user cannot see.
    @api.constrains("name", "company_id")
    def _check_name_unique_per_company(self):
        for tag in self:
            if self.search_count([
                ("id", "!=", tag.id),
                ("name", "=", tag.name),
                ("company_id", "=", tag.company_id.id),
            ]):
                raise ValidationError(_("Tag name must be unique per company."))
