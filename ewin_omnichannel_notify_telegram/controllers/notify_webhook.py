import hmac
import json
import logging

from odoo import _, http
from odoo.http import request

from ..services.notify_api_client import escape_html

_logger = logging.getLogger(__name__)

GROUP_CHAT_TYPES = ("group", "supergroup")


class TelegramNotifyWebhookController(http.Controller):
    """Updates addressed to the *notification* bot.

    It has nothing to do with the customer-facing webhook of
    ``ewin_omnichannel_telegram``: different bot, different token, different
    route. The shape is deliberately the same, because the guarantees are —
    constant-time secret comparison, no hint that an address exists, and a
    ``200`` whatever happens, so Telegram never retries an update this
    database has already seen.
    """

    @http.route("/omnichannel/notify/telegram/<string:notifier_uuid>",
                type="http", auth="public", csrf=False, methods=["POST"],
                save_session=False)
    def telegram_notify_webhook(self, notifier_uuid, **kwargs):
        notifier = request.env["omnichannel.telegram.notifier"].sudo().search(
            [("webhook_uuid", "=", notifier_uuid)], limit=1)
        if not notifier:
            return request.make_json_response({})  # do not leak existence
        stored = notifier.webhook_secret or ""
        presented = request.httprequest.headers.get(
            "X-Telegram-Bot-Api-Secret-Token") or ""
        # No stored secret means reject, never "skip the check": the URL is
        # not a credential, and Telegram's servers know it.
        if not stored or not hmac.compare_digest(presented, stored):
            _logger.warning(
                "Rejected a Telegram notify update: bad secret (notifier %s)",
                notifier.id)
            return request.make_json_response({})
        try:
            payload = json.loads(request.httprequest.get_data() or b"{}")
        except (ValueError, TypeError):
            _logger.warning("Malformed Telegram notify body (notifier %s)",
                            notifier.id)
            return request.make_json_response({})
        try:
            self._handle(notifier, payload)
        except Exception:  # noqa: BLE001 — a 200 is the point of this route
            _logger.exception("Telegram notify update failed (notifier %s)",
                              notifier.id)
            request.env.cr.rollback()
        return request.make_json_response({})

    def _handle(self, notifier, payload):
        """Two commands and silence for everything else."""
        message = payload.get("message") or {}
        text = (message.get("text") or "").strip()
        if not text.startswith("/"):
            return
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        command, _separator, argument = text.partition(" ")
        # A command addressed in a group carries the bot: /register@mybot.
        command = command.split("@", 1)[0]
        if command == "/start" and chat.get("type") == "private":
            self._link_user(notifier, chat, sender, argument.strip())
        elif command == "/register" and chat.get("type") in GROUP_CHAT_TYPES:
            self._register_group(notifier, chat, sender)

    def _link_user(self, notifier, chat, sender, token):
        users = request.env["res.users"].sudo()
        user = users._omni_tg_consume_link_token(token)
        if not user:
            self._reply(notifier, chat, _(
                "That link is not valid any more. Open Odoo, go to "
                "Preferences and press Connect Telegram again."))
            return
        user.write({
            "omni_tg_chat_id": str(chat.get("id")),
            "omni_tg_username": sender.get("username") or False,
        })
        self._reply(notifier, chat, _(
            "Done — %s will get EWIN Inbox notifications here.", user.name))

    def _register_group(self, notifier, chat, sender):
        """Adopt this group as the team chat.

        Only someone who has already linked their own Telegram *and* holds the
        administrator group may do it. The webhook address travels to
        Telegram's servers, so possession of it proves nothing.
        """
        user = request.env["res.users"].sudo().search(
            [("omni_tg_chat_id", "=", str(sender.get("id")))], limit=1)
        if not user or not user.has_group(
                "ewin_omnichannel_core.group_omni_admin"):
            _logger.info(
                "Ignored /register from an unlinked or non-admin Telegram "
                "user (notifier %s)", notifier.id)
            return
        notifier.write({"group_chat_id": str(chat.get("id"))})
        self._reply(notifier, chat, _(
            "This group will receive EWIN Inbox notifications."))

    def _reply(self, notifier, chat, text):
        """Confirm a command straight away.

        The only network call this controller makes, and it is worth it: a
        command is interactive, and waiting a cron tick for the answer reads
        as the bot ignoring you. A failure here must not undo a linking that
        has already happened, so it is logged and swallowed.
        """
        try:
            notifier._client().send_message(chat.get("id"), escape_html(text))
        except Exception:  # noqa: BLE001
            _logger.warning(
                "Could not confirm a Telegram command (notifier %s)",
                notifier.id, exc_info=True)
