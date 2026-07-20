from odoo import fields, models


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    omni_conversation_id = fields.Many2one(
        "omnichannel.conversation", string="Omnichannel Conversation",
        index=True, ondelete="set null")

    def message_post(self, *, message_type="notification", **kwargs):
        message = super().message_post(message_type=message_type, **kwargs)
        self._omni_forward_operator_reply(message)
        return message

    def _omni_forward_operator_reply(self, message):
        """§6: when an operator types directly in the linked Discuss channel,
        forward it to the customer through the connector. Our own mirror posts
        carry the ``omni_mirror`` context and are ignored to avoid a loop."""
        if self.env.context.get("omni_mirror"):
            return
        conversation = self.omni_conversation_id
        if not conversation or message.message_type != "comment":
            return
        author = message.author_id
        # only messages typed by an internal operator (not the customer mirror,
        # not OdooBot / system posts)
        if not author or not author.user_ids.filtered(lambda u: not u.share):
            return
        root = self.env.ref("base.partner_root", raise_if_not_found=False)
        if root and author == root:
            return
        if not (message.body or message.attachment_ids):
            return
        self.env["omnichannel.message.service"].sudo().create_outbound_from_discuss(
            conversation, message)
