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
                date=message._history_date(),
            )
            # Linked afterwards rather than passed as ``attachment_ids``:
            # message_post keeps only the attachments the *calling user* drafted
            # on a composer, and sudo() raises privileges without changing the
            # user — an inbound webhook still runs as the public one, so every
            # customer photo would be silently dropped. Writing the m2m is also
            # what makes the live copy carry exactly what backfill would.
            if message.attachment_ids:
                copy.sudo().attachment_ids = [
                    (6, 0, message.attachment_ids.ids)]
            message.sudo().history_message_ids = [(4, copy.id)]
        return True

    @api.model
    def _history_key(self, target):
        """What identifies the record a copy sits on.

        A contact and a lead are different models, so "is this copy on that
        target" is a ``(model, id)`` question and never a recordset
        comparison. Both the existence check and the purge ask it here, so
        there is one notion of a copy belonging to a target.
        """
        return (target._name, target.id)

    @api.model
    def _existing_copy(self, message, target):
        """The copy of ``message`` already living on ``target``, if any."""
        key = self._history_key(target)
        return message.history_message_ids.filtered(
            lambda copy: (copy.model, copy.res_id) == key)

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

    @api.model
    def backfill(self, conversation, targets):
        """Copy the conversation's whole past into records just linked to it.

        Deliberately not a loop over ``mirror``: ``message_post`` runs the
        notification machinery once per call, and a linked conversation can be
        hundreds of messages long. A batch ``create`` writes them in one go,
        which is also what lets each copy keep the timestamp of the message it
        represents — a history stamped "now" reads as a single event rather
        than a conversation. The ledger row travels in the same create, so a
        thousand-message backfill stays two statements instead of a thousand.

        ``scheduled`` and ``cancelled`` messages are excluded: the contact's
        chatter is the same promise as the thread's, and a link must not turn
        a reply the operator has only committed to — or one that will never
        go out — into an accomplished fact on the customer's own record. A
        scheduled message that later sends is picked up by the ordinary
        ``mirror()`` call ``release_scheduled`` makes; skipping it here is
        what leaves that copy free to carry the real ``sent_at`` instead of
        being pre-empted by a backfill copy stamped with ``create_date``.
        """
        subtype = self.env.ref("mail.mt_note")
        messages = conversation.omni_message_ids.filtered(
            lambda message: message.state not in ("scheduled", "cancelled")
        ).sorted("id")
        for target in targets:
            pending = messages.filtered(
                lambda message: not self._existing_copy(message, target))
            if not pending:
                continue
            self.env["mail.message"].sudo().create([{
                "model": target._name,
                "res_id": target.id,
                "body": self._history_body(message),
                "author_id": self._history_author(message).id,
                "message_type": "comment",
                "subtype_id": subtype.id,
                "date": message._history_date(),
                "attachment_ids": [(6, 0, message.attachment_ids.ids)],
                "omni_message_ids": [(6, 0, message.ids)],
            } for message in pending])
        return True

    @api.model
    def purge(self, conversation, targets):
        """Delete the copies this conversation put on records it left.

        One filtered pass over the whole ledger, not one per target: unlinking
        inside a loop would leave the recordset holding ids that no longer
        exist, and the next target's filter would read a deleted row.
        Unlinking the ``mail.message`` clears the ledger rows with it, so the
        conversation is left exactly as it was before it was ever linked.
        """
        keys = {self._history_key(target) for target in targets}
        conversation.omni_message_ids.history_message_ids.filtered(
            lambda copy: (copy.model, copy.res_id) in keys).sudo().unlink()
        return True
