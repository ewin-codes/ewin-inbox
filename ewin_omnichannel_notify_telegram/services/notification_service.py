from odoo import _, api, models

from odoo.addons.ewin_omnichannel_core.models.omnichannel_job import (
    NonRetriableError)

from .notify_api_client import TelegramNotifyError, escape_html

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
    @api.private
    def schedule(self, message):
        """Queue one notification about ``message``, if it is due.

        Runs inside the channel's own inbound transaction, so it does two
        cheap things and no more: claim the throttle window and write a queue
        row. The network call waits for the cron.

        The window is claimed here rather than after a successful send. With
        Telegram unreachable the alternative would queue a row per message and
        deliver the backlog in one burst once it came back.

        ``@api.private``: this is called from ``omnichannel.message.create()``
        with the caller's own access rights, never over RPC — a caller with
        no business seeing a conversation at all must not be able to invoke
        it directly and choose which notifier and which message to pair up.
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

    @api.model
    @api.private
    def send_notification(self, notifier_id, message_id):
        """Deliver one notification. The job queue's entry point.

        Everything is resolved now, not when the job was written: if somebody
        took the conversation while it waited, the notification is theirs.

        ``@api.private``: the job queue reaches this through
        ``getattr(target, self.method)`` in ``omnichannel.job._resolve_target``,
        never through ``call_kw``, so the decorator does not touch that path
        (``_job_methods`` is what gates it). What it closes is RPC: this
        method ``sudo()``s both ids it is given, so without it any
        authenticated caller — a portal user included — could pick an
        arbitrary notifier and message and have the bot post that message's
        sender, text and a deep link into any company's conversation, bypassing
        every record rule that normally hides it.
        """
        notifier = self.env["omnichannel.telegram.notifier"].sudo().browse(
            notifier_id).exists()
        message = self.env["omnichannel.message"].sudo().browse(
            message_id).exists()
        if not notifier or not notifier.active or not message:
            return False
        conversation = message.conversation_id
        if not notifier.bot_token:
            self._log_configuration(
                conversation, "The Telegram notifier has no bot token",
                "Paste the @BotFather token on the notifier and press Check "
                "Connection.")
            return False
        chat_id = self._resolve_chat_id(notifier, conversation)
        if not chat_id:
            self._log_configuration(
                conversation, "No Telegram recipient for a notification",
                "The conversation has no operator with a linked Telegram, and "
                "the notifier has no group chat. Send /register in the team "
                "group, or ask the operator to connect Telegram.")
            return False
        try:
            notifier._client().send_message(chat_id, self._compose(message))
        except TelegramNotifyError as err:
            self._log_failure(notifier, conversation, err)
            if not err.retriable:
                # Terminal: the queue must stop, and the notifier now says why.
                raise NonRetriableError(err.description) from err
            raise
        if notifier.state == "error":
            notifier.write({"state": "connected", "last_error": False})
        return True

    @api.model
    def _resolve_chat_id(self, notifier, conversation):
        """Who hears about this conversation.

        The assigned operator when they have linked their Telegram, the team
        group otherwise — including when nobody is assigned. A notification
        with nowhere to go is worse than a noisy group, so the group is the
        floor, not the exception.
        """
        return (conversation.operator_id.sudo().omni_tg_chat_id
                or notifier.group_chat_id
                or False)

    @api.model
    def _log_configuration(self, conversation, summary, technical):
        """Something is not set up. Not a delivery failure, so the queue row
        completes: the error log is where an administrator looks."""
        self.env["omnichannel.error.log"].sudo().log(
            "configuration", summary, account=conversation.account_id,
            conversation_id=conversation.id, technical=technical)

    @api.model
    def _log_failure(self, notifier, conversation, error):
        notifier._set_error(error.description)
        self.env["omnichannel.error.log"].sudo().log(
            "provider", str(notifier._friendly(error)), code=str(error.code),
            account=conversation.account_id,
            conversation_id=conversation.id, technical=str(error))
