import datetime

from odoo import api, fields, models

_WA_WINDOW = datetime.timedelta(hours=24)


class OmnichannelConversation(models.Model):
    _inherit = "omnichannel.conversation"

    wa_is_whatsapp = fields.Boolean(compute="_compute_wa_flags")
    wa_window_closed = fields.Boolean(compute="_compute_wa_flags")

    @api.depends("channel_id.code", "last_customer_message_at")
    def _compute_wa_flags(self):
        now = fields.Datetime.now()
        for conv in self:
            is_wa = conv.channel_id.code == "whatsapp"
            conv.wa_is_whatsapp = is_wa
            conv.wa_window_closed = is_wa and (
                not conv.last_customer_message_at
                or now - conv.last_customer_message_at > _WA_WINDOW)

    def action_wa_open_template_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Send WhatsApp Template",
            "res_model": "omnichannel.whatsapp.send_template.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_conversation_id": self.id},
        }
