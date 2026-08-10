from markupsafe import Markup, escape

from odoo import api, models

from .message_service import INTERNAL_BADGE


class HistoryService(models.AbstractModel):
    """Copies of conversation messages in the customer's own history.

    A chatter shows only the messages written on the record itself, so a
    conversation's texts reach a contact or a lead by being copied there.
    This service is the only place those copies are created and destroyed;
    every copy is recorded on ``omnichannel.message.history_message_ids`` so
    unlinking can remove exactly what linking added.
    """

    _name = "omnichannel.history.service"
    _description = "Omnichannel History Service"

    @api.model
    def mirror(self, message):
        """Copy one message into every record its conversation is linked to.

        Uses ``message_post`` rather than a bare create: it is what pushes the
        new message over the bus, so an open contact or lead form shows the
        customer's words as they arrive. The ``mail.mt_note`` subtype keeps it
        out of every follower's inbox — a chat channel would otherwise turn
        each incoming "hi" into an email.

        Runs sudo throughout: an inbound message arrives in a webhook request
        that has no real user behind it.
        """
        for target in message.conversation_id._history_targets():
            if self._existing_copy(message, target):
                continue
            copy = target.sudo().message_post(
                body=self._history_body(message),
                author_id=self._history_author(message).id,
                message_type="comment",
                subtype_xmlid="mail.mt_note",
                attachment_ids=message.attachment_ids.ids,
            )
            message.sudo().history_message_ids = [(4, copy.id)]
        return True

    @api.model
    def _existing_copy(self, message, target):
        """The copy of ``message`` already living on ``target``, if any."""
        return message.history_message_ids.filtered(
            lambda copy: copy.model == target._name
            and copy.res_id == target.id)

    @api.model
    def _history_author(self, message):
        """Who the chatter should credit for the copy.

        Same fallback chain as the Discuss mirror: the message's own author,
        then the conversation's contact, then the system partner — a copy with
        no author would be attributed to whoever triggered the mirror.
        """
        conversation = message.conversation_id
        return (message.author_partner_id or conversation.partner_id
                or self.env.ref("base.partner_root"))

    @api.model
    def _history_body(self, message):
        """The copy's body: which channel it came from, then the message.

        Author, timestamp and avatar are not rendered here — they come from
        the copy's own ``author_id`` and ``date``, which the chatter already
        knows how to display.
        """
        conversation = message.conversation_id
        channel = conversation.channel_id
        badge = conversation._channel_badge(
            channel.code or "", escape(channel.name or "Channel"), 14)
        body = Markup(message.body or "")
        if message.is_internal:
            body = INTERNAL_BADGE + body
        return Markup(
            '<div class="o_omni_history_entry">%s %s</div>') % (badge, body)
