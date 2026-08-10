import logging

from odoo import _, _lt, api, fields, models
from odoo.exceptions import UserError

from ..services.viber_api_client import ViberApiClient, ViberApiError

_logger = logging.getLogger(__name__)

# Viber send_message status codes → operator-friendly explanations.
# Module-level strings use _lt (lazy translation): _() at import time has no
# language context and would freeze the string in the source language. _lt
# defers the lookup to render time, when the user's language is known.
FRIENDLY_ERRORS = {
    1: _lt("The webhook URL is invalid."),
    2: _lt("The Viber auth token is invalid."),
    3: _lt("Viber rejected the message data."),
    5: _lt("The customer is not registered on Viber."),
    6: _lt("The customer must message the bot before it can reply."),
    7: _lt("The bot is blocked by the customer."),
    8: _lt("The Viber public account was not found."),
    9: _lt("The Viber public account is suspended."),
}

VIBER_EVENT_TYPES = ["message", "subscribed", "unsubscribed",
                     "conversation_started"]


class ViberConnector(models.AbstractModel):
    _name = "omnichannel.connector.viber"
    _inherit = "omnichannel.connector"
    _description = "Viber Connector"

    @api.model
    def _client(self, account):
        token = account.sudo().viber_auth_token
        if not token:
            raise UserError(_("Viber auth token is not set."))
        return ViberApiClient(
            token, account.viber_api_base_url or "https://chatapi.viber.com/pa")

    @api.model
    def _webhook_url(self, account):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        return f"{base}/omnichannel/viber/webhook/{account.webhook_uuid}"

    @api.model
    def connect(self, account):
        try:
            info = self._client(account).get_account_info()
        except ViberApiError as err:
            account._set_error(err.description)
            raise UserError(self._friendly(err))
        account.sudo().write({
            "viber_bot_name": account.viber_bot_name or info.get("name"),
            "viber_bot_uri": info.get("uri"),
            "viber_bot_id": info.get("id"),
            "state": "connected",
            "last_error": False,
        })
        return self._notify_ui(_("Connected as %s", info.get("name")))

    @api.model
    def register_webhook(self, account):
        # Viber validates the URL synchronously: set_webhook only returns once
        # Viber has POSTed an {"event": "webhook"} callback to us and got a 200
        # back. That callback commits a write to this account row, so both
        # outcomes below have to be persisted out of the current transaction —
        # see omnichannel.account._write_isolated.
        url = self._webhook_url(account)
        try:
            self._client(account).set_webhook(url, VIBER_EVENT_TYPES)
        except ViberApiError as err:
            account.sudo()._write_isolated({
                "state": "error", "last_error": err.description})
            raise UserError(self._friendly(err))
        account.sudo()._write_isolated({
            "viber_webhook_status": "registered",
            "state": "connected",
        })
        return self._notify_ui(_("Webhook registered."))

    @api.model
    def remove_webhook(self, account):
        try:
            self._client(account).remove_webhook()
        except ViberApiError as err:
            raise UserError(self._friendly(err))
        account.sudo().write({"viber_webhook_status": "removed"})
        return self._notify_ui(_("Webhook removed."))

    @api.model
    def viber_webhook_info(self, account):
        info = self._client(account).get_account_info()
        account.viber_webhook_status = "registered" if info.get("webhook") else "none"
        return self._notify_ui(str(info.get("webhook") or _("No webhook set.")))

    @api.model
    def parse_webhook(self, account, payload, headers):
        # NB: the X-Viber-Content-Signature HMAC is verified in the controller
        # (it needs the raw request body). By the time we get here the payload
        # is trusted, so we only run the idempotent inbound flow.
        normalizer = self.env["omnichannel.viber.normalizer"]
        event_id = normalizer.event_id_for(payload)
        event, created = self.env["omnichannel.event"].record(
            account, event_id, "message", payload)
        account.sudo().last_webhook_at = fields.Datetime.now()
        if not created and event.state in ("processed", "skipped"):
            return True
        try:
            normalized = normalizer.normalize_update(account, payload)
            if normalized is None:
                event.write({"state": "skipped"})
                return True
            self.env["omnichannel.routing.service"].process_event(
                account, normalized)
            event.mark_processed()
        except Exception as err:  # noqa: BLE001
            event.mark_failed(str(err))
            self.env["omnichannel.error.log"].log(
                "internal", "Failed to process Viber update",
                account=account, event_id=event.id, technical=str(err))
            raise
        return True

    @api.model
    def parse_webhook_job(self, account_id, payload):
        account = self.env["omnichannel.account"].browse(account_id).exists()
        if not account:
            return
        self.parse_webhook(account, payload, {})

    @api.model
    def send_message(self, account, message):
        conv = message.conversation_id
        receiver = conv.identity_id.external_id
        client = self._client(account)
        sender_name = (account.viber_bot_name or account.name or "Bot")[:28]
        try:
            if message.attachment_ids:
                result = self._send_with_attachments(
                    client, receiver, sender_name, message)
            else:
                result = client.send_message({
                    "receiver": receiver,
                    "sender": {"name": sender_name},
                    "type": "text",
                    "text": message.body_text(),
                })
        except ViberApiError as err:
            self.handle_provider_error(account, err, message=message)
            if not err.retriable:
                from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
                    import NonRetriableError
                raise NonRetriableError(self._friendly(err))
            raise
        message.write({
            "state": "sent",
            "external_message_id": str(result.get("message_token")),
            "sent_at": fields.Datetime.now(),
            "error_message": False, "error_code": False,
        })
        return True

    @api.model
    def _send_with_attachments(self, client, receiver, sender_name, message):
        """Viber sends one message per API call and media messages carry the
        media as a public URL. Send the caption as its own text message, then
        each attachment (image → picture, everything else → file)."""
        base = {"receiver": receiver, "sender": {"name": sender_name}}
        result = None
        text = message.body_text()
        if text:
            result = client.send_message({**base, "type": "text", "text": text})
        for att in message.attachment_ids:
            url = self._public_attachment_url(att)
            if (att.mimetype or "").startswith("image/"):
                result = client.send_message({
                    **base, "type": "picture", "media": url,
                    "text": att.name or ""})
            else:
                result = client.send_message({
                    **base, "type": "file", "media": url,
                    "file_name": att.name or "file", "size": att.file_size or 0})
        return result or {}

    @api.model
    def _public_attachment_url(self, attachment):
        """Build a tokenised public URL Viber's servers can fetch. The
        access_token gates the download to holders of the (unguessable) token."""
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        att = attachment.sudo()
        token = att.access_token or att.generate_access_token()[0]
        return f"{base}/web/content/{att.id}?access_token={token}&download=true"

    @api.model
    def download_attachment(self, account, provider_attachment):
        if not account.viber_download_files:
            return self.env["ir.attachment"]
        client = self._client(account)
        try:
            data = client.download_media(provider_attachment["url"])
            return self.env["omnichannel.viber.attachment.service"].store(
                account, data, provider_attachment.get("filename", "file"),
                provider_attachment.get("mime_type"))
        except Exception as err:  # noqa: BLE001 (ViberApiError + ValueError from store)
            self.env["omnichannel.error.log"].log(
                "attachment", "Failed to download Viber file",
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
            # str(): the friendly text is a lazy (_lt) translation; resolve it
            # before storing so the DB column holds a plain string.
            message.write({"error_code": vals["code"],
                           "error_message": str(summary)})
        self.env["omnichannel.error.log"].log("provider", summary, **vals)
        return summary

    @api.model
    def _friendly(self, error):
        code = getattr(error, "code", None)
        if code in FRIENDLY_ERRORS:
            return FRIENDLY_ERRORS[code]
        return _("Viber error: %s", getattr(error, "description", str(error)))

    @api.model
    def _notify_ui(self, message):
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": message, "type": "success", "sticky": False},
        }
