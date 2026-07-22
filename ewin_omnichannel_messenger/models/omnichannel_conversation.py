import datetime

from odoo import api, fields, models

# Messenger's standard-messaging window: free-form replies are only allowed
# within 24 hours of the customer's last message.
_MG_WINDOW = datetime.timedelta(hours=24)


class OmnichannelConversation(models.Model):
    _inherit = "omnichannel.conversation"

    mg_is_messenger = fields.Boolean(compute="_compute_mg_flags")
    mg_window_closed = fields.Boolean(compute="_compute_mg_flags")

    @api.depends("channel_id.code", "last_customer_message_at")
    def _compute_mg_flags(self):
        now = fields.Datetime.now()
        for conv in self:
            is_mg = conv.channel_id.code == "messenger"
            conv.mg_is_messenger = is_mg
            conv.mg_window_closed = is_mg and (
                not conv.last_customer_message_at
                or now - conv.last_customer_message_at > _MG_WINDOW)
