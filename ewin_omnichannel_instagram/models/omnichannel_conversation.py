import datetime

from odoo import api, fields, models

# Instagram's standard-messaging window: free-form replies are only allowed
# within 24 hours of the customer's last message (the Human Agent tag extends
# this to 7 days when enabled on the account).
_IG_WINDOW = datetime.timedelta(hours=24)


class OmnichannelConversation(models.Model):
    _inherit = "omnichannel.conversation"

    ig_is_instagram = fields.Boolean(compute="_compute_ig_flags")
    ig_window_closed = fields.Boolean(compute="_compute_ig_flags")

    @api.depends("channel_id.code", "last_customer_message_at")
    def _compute_ig_flags(self):
        now = fields.Datetime.now()
        for conv in self:
            is_ig = conv.channel_id.code == "instagram"
            conv.ig_is_instagram = is_ig
            conv.ig_window_closed = is_ig and (
                not conv.last_customer_message_at
                or now - conv.last_customer_message_at > _IG_WINDOW)
