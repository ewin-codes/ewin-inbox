import re

from odoo import api, fields, models

_VAR_RE = re.compile(r"\{\{(\d+)\}\}")


class WhatsAppTemplate(models.Model):
    _name = "omnichannel.whatsapp.template"
    _description = "WhatsApp Message Template"
    _order = "name, language"

    account_id = fields.Many2one(
        "omnichannel.account", required=True, ondelete="cascade", index=True)
    name = fields.Char(required=True)
    language = fields.Char(required=True)
    category = fields.Char()
    status = fields.Char()
    body_preview = fields.Text()
    components = fields.Json(default=list)
    variables_count = fields.Integer(default=0)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("wa_template_uniq", "unique(account_id, name, language)",
         "A template with this name and language already exists."),
    ]

    @api.model
    def _body_text(self, components):
        for comp in components or []:
            if (comp.get("type") or "").upper() == "BODY":
                return comp.get("text") or ""
        return ""

    @api.model
    def _count_variables(self, components):
        text = self._body_text(components)
        nums = {int(n) for n in _VAR_RE.findall(text)}
        return max(nums) if nums else 0

    def _build_components(self, variables):
        """Build the Graph 'components' payload from ordered variable values."""
        self.ensure_one()
        variables = variables or []
        params = [{"type": "text", "text": str(v)} for v in variables]
        if not params:
            return []
        return [{"type": "body", "parameters": params}]
