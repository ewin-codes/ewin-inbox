from odoo import api, fields, models


class OmnichannelTemplate(models.Model):
    _name = "omnichannel.template"
    _description = "Omnichannel Reply Template"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    shortcut = fields.Char(
        help="Optional short code (e.g. 'hello') to find the template quickly.")
    body = fields.Text(
        required=True,
        help="Message text. Use {{name}} to insert the customer's name.")
    channel_id = fields.Many2one(
        "omnichannel.channel", string="Channel",
        help="Restrict this template to one channel. Empty = all channels.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company)

    @api.model
    def render_for_conversation(self, template_id, conversation_id):
        """Return the template body with placeholders filled from the
        conversation (customer name). Used by the composer widget."""
        template = self.browse(template_id).exists()
        if not template:
            return ""
        conversation = self.env["omnichannel.conversation"].browse(
            conversation_id).exists()
        name = ""
        if conversation:
            name = (conversation.partner_id.display_name
                    or conversation.identity_id.display_name or "")
        return (template.body or "").replace("{{name}}", name)
