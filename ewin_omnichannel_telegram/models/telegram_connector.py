import logging

from odoo import _, _lt, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ewin_omnichannel_core.tools.security import secret_equals

from ..services.telegram_api_client import TelegramApiClient, TelegramApiError

_logger = logging.getLogger(__name__)

# Module-level strings use _lt (lazy translation): _() at import time has no
# language context and would freeze the string in the source language. _lt
# defers the lookup to where an entry is read, and self.env._() resolves it
# there in that environment's language — handed on lazy, it would reach
# the ORM with no environment in reach and fall back to the source text.
FRIENDLY_ERRORS = {
    "bot was blocked by the user": _lt("The user has blocked the Telegram bot."),
    "chat not found": _lt("The Telegram chat was not found."),
    "unauthorized": _lt("The Telegram bot token is invalid."),
    "not enough rights": _lt("The bot lacks the required permissions."),
}


class TelegramConnector(models.AbstractModel):
    _name = "omnichannel.connector.telegram"
    _inherit = "omnichannel.connector"
    _description = "Telegram Connector"

    @api.model
    def _client(self, account):
        token = account.sudo().tg_bot_token
        if not token:
            raise UserError(_("Telegram bot token is not set."))
        return TelegramApiClient(token, account.tg_api_base_url or
                                 "https://api.telegram.org")

    @api.model
    def _webhook_url(self, account):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        return f"{base}/omnichannel/webhook/telegram/{account.webhook_uuid}"

    @api.model
    def connect(self, account):
        try:
            me = self._client(account).get_me()
        except TelegramApiError as err:
            account._set_error(err.description)
            return self._notify_ui(self._friendly(err), kind="danger")
        account.sudo().write({
            "tg_bot_username": me.get("username"),
            "tg_bot_external_id": str(me.get("id")),
            "state": "connected",
            "last_error": False,
        })
        return self._notify_ui(_("Connected as @%s", me.get("username")))

    @api.model
    def register_webhook(self, account):
        import uuid as _uuid
        secret = account.sudo().tg_webhook_secret or _uuid.uuid4().hex
        url = self._webhook_url(account)
        try:
            self._client(account).set_webhook(url, secret)
        except TelegramApiError as err:
            account._set_error(err.description)
            return self._notify_ui(self._friendly(err), kind="danger")
        account.sudo().write({
            "tg_webhook_secret": secret,
            "tg_webhook_status": "registered",
            "state": "connected",
        })
        return self._notify_ui(_("Webhook registered."))

    @api.model
    def remove_webhook(self, account):
        try:
            self._client(account).delete_webhook()
        except TelegramApiError as err:
            return self._notify_ui(self._friendly(err), kind="danger")
        account.sudo().write({"tg_webhook_status": "removed"})
        return self._notify_ui(_("Webhook removed."))

    @api.model
    def tg_webhook_info(self, account):
        try:
            info = self._client(account).get_webhook_info()
        except TelegramApiError as err:
            account._set_error(err.description)
            return self._notify_ui(self._friendly(err), kind="danger")
        account.sudo().write({
            "tg_webhook_status": info.get("url") and "registered" or "none"})
        # The whole reply, deliberately: it carries pending_update_count and
        # last_error_message, which are what this button is opened for when
        # Telegram has the webhook on file and updates still are not arriving.
        return self._notify_ui(str(info))

    @api.model
    def tg_send_test(self, account):
        raise UserError(_("Open a conversation to send a message; "
                          "test send requires a known chat id."))

    @api.model
    def parse_webhook(self, account, payload, headers):
        secret = account.sudo().tg_webhook_secret or ""
        got = headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
        # Fail closed, like the controller and like the Meta connectors: an
        # unconfigured secret is a reason to refuse, not to wave the update through.
        if not secret_equals(got, secret):
            _logger.warning("Telegram webhook secret mismatch for account %s",
                            account.id)
            return False
        normalizer = self.env["omnichannel.telegram.normalizer"]
        event_id = normalizer.event_id_for(payload)
        event, created = self.env["omnichannel.event"].record(
            account, event_id, "message", payload)
        account.sudo().last_webhook_at = fields.Datetime.now()
        if not created and event.state in ("processed", "skipped"):
            return True  # genuine already-handled duplicate
        # pending or failed existing event -> fall through and (re)process it
        try:
            normalized = normalizer.normalize_update(account, payload)
            if normalized is None:
                event.write({"state": "skipped"})
                return True
            self.env["omnichannel.routing.service"].process_event(account, normalized)
            event.mark_processed()
        except Exception as err:  # noqa: BLE001
            event.mark_failed(str(err))
            self.env["omnichannel.error.log"].log(
                "internal", "Failed to process Telegram update",
                account=account, event_id=event.id, technical=str(err))
            raise
        return True

    @api.model
    def parse_webhook_job(self, account_id, payload, secret):
        account = self.env["omnichannel.account"].browse(account_id).exists()
        if not account:
            return
        headers = {"X-Telegram-Bot-Api-Secret-Token": secret}
        self.parse_webhook(account, payload, headers)

    @api.model
    def send_message(self, account, message):
        conv = message.conversation_id
        chat_id = conv.identity_id.external_id
        client = self._client(account)
        try:
            if message.attachment_ids:
                result = self._send_with_attachments(client, chat_id, message)
            else:
                result = client.send_message(chat_id, message.body_text())
        except TelegramApiError as err:
            self.handle_provider_error(account, err, message=message)
            if not err.retriable:
                from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
                    import NonRetriableError
                raise NonRetriableError(self._friendly(err))
            raise
        message.write({
            "state": "sent",
            "external_message_id": str(result.get("message_id")),
            "sent_at": fields.Datetime.now(),
            "error_message": False, "error_code": False,
        })
        return True

    @api.model
    def _send_with_attachments(self, client, chat_id, message):
        result = None
        caption = message.body_text()
        for att in message.attachment_ids:
            data = att.raw
            if (att.mimetype or "").startswith("image/"):
                result = client.send_photo(chat_id, data, att.name, caption)
            else:
                result = client.send_document(chat_id, data, att.name, caption)
            caption = None
        return result or {}

    @api.model
    def download_attachment(self, account, provider_attachment):
        if not account.tg_download_files:
            return self.env["ir.attachment"]
        client = self._client(account)
        try:
            file_info = client.get_file(provider_attachment["file_id"])
            data = client.download_file(file_info["file_path"])
            return self.env["omnichannel.telegram.attachment.service"].store(
                account, data, provider_attachment.get("filename", "file"),
                provider_attachment.get("mime_type"))
        except Exception as err:  # noqa: BLE001 (covers TelegramApiError + ValueError from store)
            self.env["omnichannel.error.log"].log(
                "attachment", "Failed to download Telegram file",
                account=account, technical=str(err))
            return self.env["ir.attachment"]

    @api.model
    def handle_provider_error(self, account, error, message=None):
        summary = self._friendly(error)
        vals = {"account": account, "code": str(getattr(error, "code", "")),
                "technical": getattr(error, "description", str(error))}
        if message is not None:
            vals["message_id"] = message.id
            vals["conversation_id"] = message.conversation_id.id
            message.write({"error_code": vals["code"],
                           "error_message": summary})
        self.env["omnichannel.error.log"].log("provider", summary, **vals)
        return summary

    @api.model
    def _friendly(self, error):
        desc = (getattr(error, "description", "") or "").lower()
        for key, msg in FRIENDLY_ERRORS.items():
            if key in desc:
                return self.env._(msg)
        return _("Telegram error: %s", getattr(error, "description", str(error)))
