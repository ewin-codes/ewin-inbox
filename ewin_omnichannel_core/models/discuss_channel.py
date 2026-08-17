import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


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
        """When an operator types directly in the linked Discuss channel,
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
        # Being in the channel is not authority over the customer. Sending on
        # the company's behalf is a write on the conversation, so that is what
        # is asked — of the user actually posting, in an environment stripped
        # of any sudo the caller may hold (mail sudoes the channel to serve
        # guests). A colleague who wandered into the mirror keeps their message
        # in Discuss; it simply does not leave for the customer.
        if not conversation.with_env(self.env(su=False)).has_access("write"):
            _logger.info(
                "Discuss reply on conversation %s not forwarded: %s may not "
                "write it", conversation.id, self.env.user.login)
            return
        self.env["omnichannel.message.service"].sudo().create_outbound_from_discuss(
            conversation, message)
