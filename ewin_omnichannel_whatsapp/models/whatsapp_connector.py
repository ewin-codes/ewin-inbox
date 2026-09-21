import hashlib
import hmac
import logging

from odoo import _, _lt, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ewin_omnichannel_core.tools.security import secret_equals

from ..services.whatsapp_api_client import WhatsAppApiClient, WhatsAppApiError

_logger = logging.getLogger(__name__)

# Module-level strings use _lt (lazy translation): _() at import time has no
# language context and would freeze the string in the source language while
# emitting a "no translation language detected" warning. _lt defers the
# lookup to render time, when the user's language is known.
FRIENDLY_ERRORS = {
    131047: _lt("The customer has not messaged in the last 24 hours — only "
                "approved templates can be sent until they reply."),
    131051: _lt("This message type is not allowed outside the 24-hour window."),
    131026: _lt("The message could not be delivered (recipient unavailable or "
                "not on WhatsApp)."),
    190: _lt("The WhatsApp access token is invalid or expired."),
}


class WhatsAppConnector(models.AbstractModel):
    _name = "omnichannel.connector.whatsapp"
    _inherit = "omnichannel.connector"
    _description = "WhatsApp Connector"

    _STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3}

    @api.model
    def _client(self, account):
        account = account.sudo()
        if not account.wa_access_token or not account.wa_phone_number_id:
            raise UserError(_("WhatsApp access token / phone number ID is "
                              "not set."))
        return WhatsAppApiClient(
            account.wa_access_token, account.wa_phone_number_id,
            account.wa_waba_id, account.wa_graph_version or "v21.0")

    @api.model
    def _verify_signature(self, account, raw_body, headers):
        secret = account.sudo().wa_app_secret
        if not secret:
            _logger.warning(
                "WhatsApp webhook rejected: no App Secret configured for "
                "account %s; cannot verify signature.", account.id)
            return False
        header = headers.get("X-Hub-Signature-256") or ""
        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return secret_equals(header, expected)

    @api.model
    def connect(self, account):
        try:
            info = self._client(account).get_phone_number()
        except WhatsAppApiError as err:
            account._set_error(err.message)
            raise UserError(self._friendly(err))
        account.sudo().write({
            "wa_business_phone": info.get("display_phone_number"),
            "state": "connected", "last_error": False})
        return self._notify_ui(
            _("Connected: %s", info.get("display_phone_number") or "OK"))

    @api.model
    def parse_webhook(self, account, payload, headers):
        normalizer = self.env["omnichannel.whatsapp.normalizer"]
        account.sudo().last_webhook_at = fields.Datetime.now()
        for kind, value, item in normalizer.iter_changes(payload):
            if kind == "message":
                self._handle_message(account, value, item)
            elif kind == "status":
                self.apply_status(account, item)
        return True

    @api.model
    def _handle_message(self, account, value, message):
        normalizer = self.env["omnichannel.whatsapp.normalizer"]
        event_id = normalizer.event_id_for(message.get("id"))
        event, created = self.env["omnichannel.event"].record(
            account, event_id, "message", message)
        if not created and event.state in ("processed", "skipped"):
            return
        try:
            normalized = normalizer.normalize_message(
                account, value, message, value.get("contacts"))
            self.env["omnichannel.routing.service"].process_event(
                account, normalized)
            event.mark_processed()
        except Exception as err:  # noqa: BLE001
            event.mark_failed(str(err))
            self.env["omnichannel.error.log"].log(
                "internal", "Failed to process WhatsApp message",
                account=account, event_id=event.id, technical=str(err))
            raise

    @api.model
    def parse_webhook_job(self, account_id, payload, signature):
        account = self.env["omnichannel.account"].browse(account_id).exists()
        if not account:
            return
        self.parse_webhook(account, payload, {})

    @api.model
    def apply_status(self, account, status):
        ext_id = status.get("id")
        if not ext_id:
            return False
        message = self.env["omnichannel.message"].search([
            ("account_id", "=", account.id),
            ("external_message_id", "=", ext_id),
            ("direction", "=", "outbound"),
        ], limit=1)
        if not message:
            return False
        new_state = status.get("status")
        now = fields.Datetime.now()
        if new_state == "failed":
            current = self._STATUS_RANK.get(message.state, 0)
            if current >= 2:
                return False  # already delivered/read: ignore late failure
            errors = status.get("errors") or [{}]
            err = errors[0]
            message.write({
                "state": "failed",
                "error_code": str(err.get("code", "")),
                "error_message": err.get("title") or err.get("message")
                or self._friendly_status_error(err)})
            message.conversation_id._notify_omni_event("message_failed")
            return True
        rank = self._STATUS_RANK.get(new_state)
        current = self._STATUS_RANK.get(message.state, 0)
        if rank is None or rank <= current:
            return False  # unknown or backward transition: ignore
        vals = {"state": new_state}
        if new_state == "delivered":
            vals["delivered_at"] = now
        elif new_state == "read":
            vals["read_at"] = now
            if not message.delivered_at:
                vals["delivered_at"] = now
        message.write(vals)
        return True

    @api.model
    def _friendly_status_error(self, err):
        code = err.get("code")
        if code in FRIENDLY_ERRORS:
            return FRIENDLY_ERRORS[code]
        return err.get("title") or _("Delivery failed.")

    @api.model
    def send_message(self, account, message):
        conv = message.conversation_id
        to = conv.identity_id.external_id
        client = self._client(account)
        try:
            if message.attachment_ids:
                result = self._send_with_attachments(client, to, message)
            else:
                result = client.send_text(to, message.body_text())
        except WhatsAppApiError as err:
            self.handle_provider_error(account, err, message=message)
            if not err.retriable:
                from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
                    import NonRetriableError
                raise NonRetriableError(self._friendly(err))
            raise
        msg_id = (result.get("messages") or [{}])[0].get("id")
        message.write({
            "state": "sent", "external_message_id": msg_id,
            "sent_at": fields.Datetime.now(),
            "error_message": False, "error_code": False})
        return True

    @api.model
    def _send_with_attachments(self, client, to, message):
        result = None
        caption = message.body_text()
        for att in message.attachment_ids:
            mime = (att.mimetype or "application/octet-stream")
            if mime.startswith("image/"):
                media_type = "image"
            elif mime.startswith("video/"):
                media_type = "video"
            elif mime.startswith("audio/"):
                media_type = "audio"
            else:
                media_type = "document"
            media_id = client.upload_media(att.raw, att.name, mime)
            result = client.send_media(
                to, media_type, media_id, caption=caption or None,
                filename=att.name if media_type == "document" else None)
            caption = None  # caption only on the first media
        return result or {}

    @api.model
    def sync_templates(self, account):
        Template = self.env["omnichannel.whatsapp.template"]
        remote = self._client(account).list_templates()
        seen = Template
        for tpl in remote:
            if tpl.get("status") != "APPROVED":
                continue
            components = tpl.get("components") or []
            vals = {
                "account_id": account.id,
                "name": tpl.get("name"),
                "language": tpl.get("language"),
                "category": tpl.get("category"),
                "status": tpl.get("status"),
                "components": components,
                "body_preview": Template._body_text(components),
                "variables_count": Template._count_variables(components),
                "active": True,
            }
            existing = Template.with_context(active_test=False).search([
                ("account_id", "=", account.id),
                ("name", "=", tpl.get("name")),
                ("language", "=", tpl.get("language")),
            ], limit=1)
            if existing:
                existing.write(vals)
                seen |= existing
            else:
                seen |= Template.create(vals)
        # archive templates no longer present/approved remotely
        stale = Template.with_context(active_test=False).search([
            ("account_id", "=", account.id), ("id", "not in", seen.ids),
            ("active", "=", True)])
        stale.write({"active": False})
        return self._notify_ui(_("Synced %s template(s).", len(seen)))

    @api.model
    def send_template(self, account, conversation, template, variables):
        if len(variables or []) != template.variables_count:
            raise UserError(_(
                "This template expects %s variable(s) but %s were "
                "provided.", template.variables_count, len(variables or [])))
        to = conversation.identity_id.external_id
        client = self._client(account)
        components = template._build_components(variables)
        try:
            result = client.send_template(
                to, template.name, template.language, components)
        except WhatsAppApiError as err:
            self.handle_provider_error(account, err)
            raise
        rendered = template.body_preview or template.name
        for i, val in enumerate(variables or [], start=1):
            rendered = rendered.replace("{{%d}}" % i, str(val))
        now = fields.Datetime.now()
        msg_id = (result.get("messages") or [{}])[0].get("id")
        message = self.env["omnichannel.message"].create({
            "conversation_id": conversation.id, "direction": "outbound",
            "sender_type": "operator", "message_type": "text",
            "body": rendered, "author_partner_id": self.env.user.partner_id.id,
            "state": "sent", "external_message_id": msg_id, "sent_at": now})
        self.env["omnichannel.message.service"]._mirror_to_discuss(
            conversation, message)
        # A template is the operator re-opening the 24-hour window, so it is
        # part of what the customer was told and belongs in their history like
        # any other reply. The message is built here rather than through
        # omnichannel.message.service because the provider call already
        # happened — create_outbound would queue a second, plain-text delivery.
        self.env["omnichannel.history.service"].mirror(message)
        conversation.write({"last_message_at": now,
                            "last_operator_message_at": now})
        return message

    @api.model
    def download_attachment(self, account, provider_attachment):
        if not account.wa_download_files:
            return self.env["ir.attachment"]
        client = self._client(account)
        try:
            url, mime = client.get_media_url(provider_attachment["media_id"])
            data = client.download_media(url)
            return self.env["omnichannel.whatsapp.attachment.service"].store(
                account, data,
                provider_attachment.get("filename", "file"),
                provider_attachment.get("mime_type") or mime)
        except Exception as err:  # noqa: BLE001
            self.env["omnichannel.error.log"].log(
                "attachment", "Failed to download WhatsApp media",
                account=account, technical=str(err))
            return self.env["ir.attachment"]

    @api.model
    def handle_provider_error(self, account, error, message=None):
        summary = self._friendly(error)
        vals = {"account": account, "code": str(getattr(error, "code", "")),
                "technical": getattr(error, "message", str(error))}
        if message is not None:
            vals["message_id"] = message.id
            vals["conversation_id"] = message.conversation_id.id
            message.write({"error_code": vals["code"], "error_message": summary})
        self.env["omnichannel.error.log"].log("provider", summary, **vals)
        return summary

    @api.model
    def _friendly(self, error):
        code = getattr(error, "code", None)
        if code in FRIENDLY_ERRORS:
            return FRIENDLY_ERRORS[code]
        return _("WhatsApp error: %s", getattr(error, "message", str(error)))

    @api.model
    def _notify_ui(self, message):
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": message, "type": "success", "sticky": False},
        }
