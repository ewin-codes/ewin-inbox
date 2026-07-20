from odoo import _, fields, models


class OmnichannelConversation(models.Model):
    _inherit = "omnichannel.conversation"

    livechat_channel_id = fields.Many2one(
        "discuss.channel", string="Live Chat Session", copy=False, index=True,
        help="The current livechat discuss.channel that transports this "
             "conversation to the visitor.")

    def action_close(self):
        res = super().action_close()
        for conv in self.filtered("livechat_channel_id"):
            channel = conv.livechat_channel_id
            if not channel.exists() or not channel.livechat_active:
                continue
            operator_partner = channel.livechat_operator_id \
                or conv.account_id.livechat_bridge_user_id.partner_id
            channel.sudo().with_context(
                omni_livechat_outbound=True).message_post(
                body=_("The operator has closed this conversation."),
                author_id=operator_partner.id,
                message_type="comment",
                subtype_xmlid="mail.mt_comment")
            channel.sudo()._close_livechat_session()
        return res
