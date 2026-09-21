from odoo import _, api, models

from .notify_api_client import escape_html

# How much of the customer's own text a notification carries. Long enough to
# recognise the question, short enough that the operator still opens Odoo.
BODY_PREVIEW_LIMIT = 200


class TelegramNotificationService(models.AbstractModel):
    _name = "omnichannel.telegram.notification.service"
    _description = "Telegram Notification Service"

    # The one method omnichannel.job may call here. The queue drains as
    # superuser, so a row is an instruction to the database owner: what it may
    # name is not "any method" but one this model published.
    # See omnichannel.job._resolve_target.
    _job_methods = frozenset({"send_notification"})

    @api.model
    def schedule(self, message):
        """Queue one notification about ``message``, if it is due.

        Runs inside the channel's own inbound transaction, so it does two
        cheap things and no more: claim the throttle window and write a queue
        row. The network call waits for the cron.

        The window is claimed here rather than after a successful send. With
        Telegram unreachable the alternative would queue a row per message and
        deliver the backlog in one burst once it came back.
        """
        conversation = message.conversation_id
        notifier = self.env["omnichannel.telegram.notifier"]._for_company(
            conversation.company_id)
        if not notifier:
            return False
        if not conversation._tg_claim_notification(notifier.throttle_minutes):
            return False
        self.env["omnichannel.job"].sudo().enqueue(
            model=self._name,
            method="send_notification",
            args={"notifier_id": notifier.id, "message_id": message.id},
            company_id=conversation.company_id.id,
        )
        return True

    @api.model
    def _compose(self, message):
        """The notification, in Telegram's HTML parse mode.

        Three lines: who wrote and where, what they said, and the way back
        into Odoo. Every value that came from outside is escaped — including
        the link, whose query string carries an ``&``.
        """
        conversation = message.conversation_id
        channel = conversation.channel_id.name or conversation.account_id.name
        url = conversation._notify_get_action_link("view")
        lines = [
            "<b>%s</b> — %s" % (escape_html(channel),
                                escape_html(self._sender_label(conversation))),
            escape_html(self._preview(message)),
            '<a href="%s">%s</a>' % (escape_html(url),
                                     escape_html(_("Open conversation"))),
        ]
        return "\n".join(line for line in lines if line)

    @api.model
    def _sender_label(self, conversation):
        """The customer as a person would name them.

        The handle is appended when it adds something: on chat channels it is
        the @username, which is how the operator will address them back, and
        it tells two same-named people apart.
        """
        name = conversation.partner_id.name or conversation.identity_id.display_name
        handle = conversation.identity_handle
        if name and handle and handle != name:
            return f"{name} ({handle})"
        return name or handle or _("Unknown sender")

    @api.model
    def _preview(self, message):
        """The opening of the customer's text, whitespace collapsed.

        ``body`` is ``fields.Html``; Telegram gets plain text. A message with
        no text at all — a photo, a location — is named by its type instead,
        because a notification that says nothing is worse than none.
        """
        text = " ".join((message.body_text() or "").split())
        if not text:
            labels = dict(
                message._fields["message_type"]._description_selection(self.env))
            return "[%s]" % labels.get(message.message_type, message.message_type)
        if len(text) <= BODY_PREVIEW_LIMIT:
            return text
        return text[:BODY_PREVIEW_LIMIT].rstrip() + "…"
