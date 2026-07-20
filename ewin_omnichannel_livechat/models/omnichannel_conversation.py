from odoo import fields, models


class OmnichannelConversation(models.Model):
    _inherit = "omnichannel.conversation"

    livechat_channel_id = fields.Many2one(
        "discuss.channel", string="Live Chat Session", copy=False, index=True,
        help="The current livechat discuss.channel that transports this "
             "conversation to the visitor.")
