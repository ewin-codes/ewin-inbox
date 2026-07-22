import datetime
import hashlib
import hmac
import logging

from odoo import _, _lt, api, fields, models
from odoo.exceptions import UserError

from ..services.messenger_api_client import MessengerApiClient, MessengerApiError

_logger = logging.getLogger(__name__)

# Module-level strings use _lt (lazy translation): _() at import time has no
# language context and would freeze the string in the source language. _lt
# defers the lookup to render time, when the user's language is known.
FRIENDLY_ERRORS = {
    10: _lt("This message is outside the 24-hour messaging window — the "
            "customer must reply before you can message them again."),
    551: _lt("This person is currently unavailable on Messenger."),
    190: _lt("The Facebook Page access token is invalid or has expired."),
    200: _lt("The app doesn't have permission to message this person."),
    # Code 100 is context-dependent (bad recipient, unknown field, missing
    # metadata permission, ...); its raw Graph message is more actionable than
    # any fixed text, so it is deliberately not mapped here.
}

# Graph error codes that mean "the token works but lacks access to this Page's
# public metadata (e.g. its name)" — a read the messaging bot does not need.
_PAGE_METADATA_DENIED_CODES = {100, 200}


class MessengerConnector(models.AbstractModel):
    _name = "omnichannel.connector.messenger"
    _inherit = "omnichannel.connector"
    _description = "Messenger Connector"

    _STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3}

    # --- client / auth ---
    @api.model
    def _client(self, account):
        account = account.sudo()
        if not account.mg_page_access_token or not account.mg_page_id:
            raise UserError(_("Messenger Page access token / Page ID is not "
                              "set."))
        return MessengerApiClient(
            account.mg_page_access_token, account.mg_page_id,
            account.mg_graph_version or "v21.0")

    @api.model
    def _verify_signature(self, account, raw_body, headers):
        """Verify Meta's ``X-Hub-Signature-256`` (HMAC-SHA256 of the raw body
        keyed with the App Secret). Fails closed when no secret is set."""
        secret = account.sudo().mg_app_secret
        if not secret:
            _logger.warning(
                "Messenger webhook rejected: no App Secret configured for "
                "account %s; cannot verify signature.", account.id)
            return False
        header = headers.get("X-Hub-Signature-256") or ""
        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(header, expected)

    @api.model
    def connect(self, account):
        try:
            info = self._client(account).get_page()
        except MessengerApiError as err:
            # Reading the Page name needs 'pages_read_engagement' / Page public
            # metadata access, which a messaging bot does not require. Don't
            # hard-fail the health check on that — the token is still
            # messaging-capable. Only a bad/expired token or a transport error
            # is a genuine connection failure.
            if err.code in _PAGE_METADATA_DENIED_CODES:
                # Success: the token is valid and messaging-ready. Reading the
                # Page name is optional (needs pages_read_engagement), so this
                # is a green "connected", not a warning — nothing is required
                # from the user.
                account.sudo().write({"state": "connected", "last_error": False})
                return self._notify_ui(
                    _("Connected. Messaging is ready. (The Page name is "
                      "optional and not shown — it needs the "
                      "'pages_read_engagement' permission.)"))
            account._set_error(err.message)
            raise UserError(self._friendly(err))
        account.sudo().write({
            "mg_page_name": info.get("name"),
            "state": "connected", "last_error": False})
        return self._notify_ui(_("Connected: %s", info.get("name") or "OK"))

    # --- inbound webhook ---
    @api.model
    def parse_webhook(self, account, payload, headers):
        normalizer = self.env["omnichannel.messenger.normalizer"]
        account.sudo().last_webhook_at = fields.Datetime.now()
        for kind, entry, messaging in normalizer.iter_messaging(payload):
            if not self._entry_belongs_to_account(account, entry):
                continue
            if kind == "message":
                self._handle_message(account, messaging)
            elif kind == "postback":
                self._handle_postback(account, messaging)
            elif kind == "delivery":
                self.apply_delivery(account, messaging)
            elif kind == "read":
                self.apply_read(account, messaging)
            # echo (our own outgoing message reflected back), reaction and
            # other event types are intentionally ignored — see README.
        return True

    @api.model
    def _entry_belongs_to_account(self, account, entry):
        """Sanity-check the webhook entry's Page id against the account.

        Messenger puts the Page id in ``entry.id``. When the account already
        knows its Page id, a mismatching entry is dropped (defense in depth: a
        payload for another Page must not be processed here). When the Page id
        is blank it is learned from the first event — so the field need not be
        filled by hand.
        """
        page_id = (entry or {}).get("id")
        configured = account.mg_page_id
        if not configured:
            if page_id:
                account.sudo().mg_page_id = page_id
            return True
        if page_id and str(page_id) != str(configured):
            _logger.warning(
                "Messenger webhook entry for page %s does not match account "
                "%s (page %s); skipping.", page_id, account.id, configured)
            return False
        return True

    @api.model
    def _handle_message(self, account, messaging):
        normalizer = self.env["omnichannel.messenger.normalizer"]
        mid = (messaging.get("message") or {}).get("mid")
        if not mid:
            return
        event, created = self.env["omnichannel.event"].record(
            account, normalizer.event_id_for(mid), "message", messaging)
        if not created and event.state in ("processed", "skipped"):
            return
        self._process_event(account, event, normalizer.normalize_messaging(
            account, messaging))

    @api.model
    def _handle_postback(self, account, messaging):
        normalizer = self.env["omnichannel.messenger.normalizer"]
        normalized = normalizer.normalize_postback(account, messaging)
        event, created = self.env["omnichannel.event"].record(
            account, normalized["event_id"], "postback", messaging)
        if not created and event.state in ("processed", "skipped"):
            return
        self._process_event(account, event, normalized)

    @api.model
    def _process_event(self, account, event, normalized):
        if normalized is None:
            event.write({"state": "skipped"})
            return
        try:
            self._maybe_enrich_profile(account, normalized["external_user"])
            self.env["omnichannel.routing.service"].process_event(
                account, normalized)
            event.mark_processed()
        except Exception as err:  # noqa: BLE001
            event.mark_failed(str(err))
            self.env["omnichannel.error.log"].log(
                "internal", "Failed to process Messenger event",
                account=account, event_id=event.id, technical=str(err))
            raise

    @api.model
    def parse_webhook_job(self, account_id, payload, signature):
        account = self.env["omnichannel.account"].browse(account_id).exists()
        if not account:
            return
        self.parse_webhook(account, payload, {})

    @api.model
    def _maybe_enrich_profile(self, account, external_user):
        """Fill the customer's display name from the Graph profile API.

        Messenger webhooks carry only the PSID, so a brand-new contact would
        otherwise be named "Messenger user <id>". We fetch the profile only
        for identities we have not named yet — best effort: a permission or
        network error is logged and the flow continues with the fallback name.
        """
        if not account.mg_fetch_profile:
            return
        psid = external_user.get("id")
        if not psid:
            return
        existing = self.env["omnichannel.identity"].search([
            ("account_id", "=", account.id), ("external_id", "=", str(psid)),
        ], limit=1)
        if existing and existing.display_name:
            return
        try:
            profile = self.get_external_profile(account, psid)
        except MessengerApiError as err:
            _logger.info("Could not fetch Messenger profile for %s: %s",
                         psid, err)
            return
        name = " ".join(
            p for p in (profile.get("first_name"), profile.get("last_name"))
            if p).strip()
        if name:
            external_user["name"] = name
        if profile.get("profile_pic"):
            external_user.setdefault("raw", {})["profile_pic"] = \
                profile["profile_pic"]

    @api.model
    def get_external_profile(self, account, external_user_id):
        return self._client(account).get_user_profile(external_user_id)

    # --- delivery / read receipts (watermark based) ---
    @api.model
    def apply_delivery(self, account, messaging):
        delivery = messaging.get("delivery") or {}
        messages = self._receipt_targets(
            account, delivery, states=("sent",))
        for message in messages:
            self._advance_status(message, "delivered")
        return bool(messages)

    @api.model
    def apply_read(self, account, messaging):
        read = messaging.get("read") or {}
        messages = self._receipt_targets(
            account, read, states=("sent", "delivered"))
        for message in messages:
            self._advance_status(message, "read")
        return bool(messages)

    @api.model
    def _receipt_targets(self, account, receipt, states):
        """Resolve which outbound messages a delivery/read receipt covers.

        A delivery receipt may name explicit ``mids``; otherwise (and always
        for reads) Messenger sends a ``watermark`` timestamp meaning "every
        message up to this moment". We match on send time in that case.
        """
        Message = self.env["omnichannel.message"]
        mids = receipt.get("mids") or []
        if mids:
            return Message.search([
                ("account_id", "=", account.id),
                ("direction", "=", "outbound"),
                ("external_message_id", "in", mids),
            ])
        watermark = self._watermark_dt(receipt.get("watermark"))
        if not watermark:
            return Message
        return Message.search([
            ("account_id", "=", account.id),
            ("direction", "=", "outbound"),
            ("state", "in", list(states)),
            ("sent_at", "!=", False),
            ("sent_at", "<=", watermark),
        ])

    @api.model
    def _watermark_dt(self, watermark):
        try:
            seconds = int(watermark) / 1000.0
        except (TypeError, ValueError):
            return None
        # Odoo stores datetimes as naive UTC, so drop the tzinfo after building
        # a timezone-aware value (utcfromtimestamp is deprecated in 3.12).
        return datetime.datetime.fromtimestamp(
            seconds, datetime.timezone.utc).replace(tzinfo=None)

    @api.model
    def _advance_status(self, message, new_state):
        """Move a message forward through sent -> delivered -> read only.
        Duplicate or out-of-order receipts never move it backwards."""
        rank = self._STATUS_RANK.get(new_state)
        current = self._STATUS_RANK.get(message.state, 0)
        if rank is None or rank <= current:
            return False
        now = fields.Datetime.now()
        vals = {"state": new_state}
        if new_state == "delivered":
            vals["delivered_at"] = now
        elif new_state == "read":
            vals["read_at"] = now
            if not message.delivered_at:
                vals["delivered_at"] = now
        message.write(vals)
        return True

    # --- outbound ---
    @api.model
    def send_message(self, account, message):
        recipient = message.conversation_id.identity_id.external_id
        client = self._client(account)
        try:
            if message.attachment_ids:
                result = self._send_with_attachments(client, recipient, message)
            else:
                result = client.send_text(recipient, message.body_text())
        except MessengerApiError as err:
            self.handle_provider_error(account, err, message=message)
            if not err.retriable:
                from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
                    import NonRetriableError
                raise NonRetriableError(self._friendly(err))
            raise
        message.write({
            "state": "sent", "external_message_id": result.get("message_id"),
            "sent_at": fields.Datetime.now(),
            "error_message": False, "error_code": False})
        return True

    @api.model
    def _send_with_attachments(self, client, recipient, message):
        # A Messenger attachment message cannot carry text, so any caption is
        # delivered first as its own text message, then each file follows.
        result = None
        caption = message.body_text()
        if caption:
            result = client.send_text(recipient, caption)
        for att in message.attachment_ids:
            result = client.send_attachment(
                recipient, self._attachment_type(att.mimetype), att.raw,
                att.name, att.mimetype)
        return result or {}

    @api.model
    def _attachment_type(self, mimetype):
        mime = (mimetype or "").lower()
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("audio/"):
            return "audio"
        return "file"

    @api.model
    def download_attachment(self, account, provider_attachment):
        if not account.mg_download_files:
            return self.env["ir.attachment"]
        url = provider_attachment.get("url")
        if not url:
            return self.env["ir.attachment"]
        try:
            data, content_type = self._client(account).download(url)
            return self.env["omnichannel.messenger.attachment.service"].store(
                account, data, provider_attachment.get("filename", "file"),
                content_type or provider_attachment.get("mime_type"))
        except Exception as err:  # noqa: BLE001 (MessengerApiError + store ValueError)
            self.env["omnichannel.error.log"].log(
                "attachment", "Failed to download Messenger attachment",
                account=account, technical=str(err))
            return self.env["ir.attachment"]

    # --- errors ---
    @api.model
    def handle_provider_error(self, account, error, message=None):
        summary = self._friendly(error)
        vals = {"account": account, "code": str(getattr(error, "code", "")),
                "technical": getattr(error, "message", str(error))}
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
        return _("Messenger error: %s", getattr(error, "message", str(error)))

    @api.model
    def _notify_ui(self, message, type_="success"):
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": message, "type": type_,
                       "sticky": type_ != "success"},
        }
