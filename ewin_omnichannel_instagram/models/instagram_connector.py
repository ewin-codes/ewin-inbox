import datetime
import hashlib
import hmac
import logging

from odoo import _, _lt, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ewin_omnichannel_core.tools.security import secret_equals

from ..services.instagram_api_client import (
    InstagramApiClient, InstagramApiError)

_logger = logging.getLogger(__name__)

# Module-level strings use _lt (lazy translation): _() at import time has no
# language context and would freeze the string in the source language. _lt
# defers the lookup to where an entry is read, and self.env._() resolves it
# there in that environment's language — handed on lazy, it would reach
# the ORM with no environment in reach and fall back to the source text.
FRIENDLY_ERRORS = {
    10: _lt("This message is outside the 24-hour messaging window — the "
            "customer must reply before you can message them again (or enable "
            "the Human Agent tag)."),
    551: _lt("This person is currently unavailable on Instagram."),
    190: _lt("The Instagram access token is invalid or has expired."),
    200: _lt("The app doesn't have permission to message this person."),
    # Code 100 is context-dependent (bad recipient, unknown field, ...); its
    # raw Graph message is more actionable than any fixed text, so it is
    # deliberately not mapped here.
}


class InstagramConnector(models.AbstractModel):
    _name = "omnichannel.connector.instagram"
    _inherit = "omnichannel.connector"
    _description = "Instagram Connector"

    _STATUS_RANK = {"sent": 1, "delivered": 2, "read": 3}

    # --- client / auth ---
    @api.model
    def _client(self, account):
        account = account.sudo()
        if not account.ig_access_token:
            raise UserError(_("Instagram access token is not set."))
        return InstagramApiClient(
            account.ig_access_token, account.ig_user_id,
            account.ig_graph_version or "v21.0")

    @api.model
    def _verify_signature(self, account, raw_body, headers):
        """Verify Meta's ``X-Hub-Signature-256`` (HMAC-SHA256 of the raw body
        keyed with the App Secret). Fails closed when no secret is set."""
        secret = account.sudo().ig_app_secret
        if not secret:
            _logger.warning(
                "Instagram webhook rejected: no App Secret configured for "
                "account %s; cannot verify signature.", account.id)
            return False
        header = headers.get("X-Hub-Signature-256") or ""
        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return secret_equals(header, expected)

    @api.model
    def connect(self, account):
        try:
            info = self._client(account).get_me()
        except InstagramApiError as err:
            account._set_error(err.message)
            return self._notify_ui(self._friendly(err), kind="danger")
        account.sudo().write({
            "ig_user_id": info.get("user_id") and str(info["user_id"]),
            "ig_username": info.get("username"),
            "state": "connected", "last_error": False})
        return self._notify_ui(_(
            "Connected: @%s", info.get("username") or "OK"))

    # --- inbound webhook ---
    @api.model
    def parse_webhook(self, account, payload, headers):
        normalizer = self.env["omnichannel.instagram.normalizer"]
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
        """Sanity-check the webhook entry's Instagram account id.

        Instagram puts the business account id in ``entry.id``. When the
        account already knows its id, a mismatching entry is dropped (defense
        in depth: a payload for another account must not be processed here).
        When the id is blank it is learned from the first event — so the field
        need not be filled by hand.
        """
        ig_id = (entry or {}).get("id")
        configured = account.ig_user_id
        if not configured:
            if ig_id:
                account.sudo().ig_user_id = str(ig_id)
            return True
        if ig_id and str(ig_id) != str(configured):
            _logger.warning(
                "Instagram webhook entry for account %s does not match "
                "account %s (ig %s); skipping.", ig_id, account.id, configured)
            return False
        return True

    @api.model
    def _handle_message(self, account, messaging):
        normalizer = self.env["omnichannel.instagram.normalizer"]
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
        normalizer = self.env["omnichannel.instagram.normalizer"]
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
                "internal", "Failed to process Instagram event",
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

        Instagram webhooks carry only the IGSID, so a brand-new contact would
        otherwise be named "Instagram user <id>". We fetch the profile only for
        identities we have not named yet — best effort: a permission or network
        error is logged and the flow continues with the fallback name.
        """
        if not account.ig_fetch_profile:
            return
        igsid = external_user.get("id")
        if not igsid:
            return
        existing = self.env["omnichannel.identity"].search([
            ("account_id", "=", account.id), ("external_id", "=", str(igsid)),
        ], limit=1)
        if existing and existing.display_name:
            return
        try:
            profile = self.get_external_profile(account, igsid)
        except InstagramApiError as err:
            _logger.info("Could not fetch Instagram profile for %s: %s",
                         igsid, err)
            return
        name = profile.get("name") or profile.get("username")
        if name:
            external_user["name"] = name
        if profile.get("username"):
            external_user["username"] = profile["username"]
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

        A delivery receipt may name an explicit ``mid``; otherwise (and always
        for reads) Instagram sends a ``watermark`` timestamp meaning "every
        message up to this moment". We match on send time in that case.
        """
        Message = self.env["omnichannel.message"]
        mids = receipt.get("mids") or ([receipt["mid"]]
                                       if receipt.get("mid") else [])
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
        tag = self._messaging_tag(account, message.conversation_id)
        try:
            if message.attachment_ids:
                result = self._send_with_attachments(
                    client, recipient, message, tag)
            else:
                result = client.send_text(
                    recipient, message.body_text(), tag=tag)
        except InstagramApiError as err:
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
    def _messaging_tag(self, account, conversation):
        """Return the ``HUMAN_AGENT`` tag when the standard 24h window is closed
        and the account opted into it, else None (a plain ``RESPONSE``). The tag
        extends the reply window to 7 days for human agents, but needs Meta's
        Human Agent feature approved — hence it is opt-in."""
        if account.ig_human_agent and conversation.ig_window_closed:
            return "HUMAN_AGENT"
        return None

    @api.model
    def _send_with_attachments(self, client, recipient, message, tag=None):
        # An Instagram attachment message cannot carry text, so any caption is
        # delivered first as its own text message, then each file follows.
        result = None
        caption = message.body_text()
        if caption:
            result = client.send_text(recipient, caption, tag=tag)
        for att in message.attachment_ids:
            result = client.send_attachment(
                recipient, self._attachment_type(att.mimetype), att.raw,
                att.name, att.mimetype, tag=tag)
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
        if not account.ig_download_files:
            return self.env["ir.attachment"]
        url = provider_attachment.get("url")
        if not url:
            return self.env["ir.attachment"]
        try:
            data, content_type = self._client(account).download(url)
            return self.env["omnichannel.instagram.attachment.service"].store(
                account, data, provider_attachment.get("filename", "file"),
                content_type or provider_attachment.get("mime_type"))
        except Exception as err:  # noqa: BLE001 (InstagramApiError + store ValueError)
            self.env["omnichannel.error.log"].log(
                "attachment", "Failed to download Instagram attachment",
                account=account, technical=str(err))
            return self.env["ir.attachment"]

    # --- token maintenance ---
    @api.model
    def refresh_token(self, account):
        """Refresh the long-lived Instagram token and store the new expiry.

        Returns True on success, and never raises. The daily cron calls it
        once per account with no guard of its own, and the manual button
        reports a False by reading what the failure recorded here - which
        only survives because nothing raises: Odoo commits a request that
        returns, and rolls back one that does not.

        Every failure writes its reason to ``last_error`` - that is what
        the button shows - and a successful refresh clears it. Only a
        failure the account cannot recover from on its own also flips the
        state: a transient one is not a reason to park the account in
        error, and the daily cron will come round again.
        """
        account = account.sudo()
        if not account.ig_access_token:
            account._set_error(_("No Instagram access token to refresh."))
            return False
        try:
            data = self._client(account).refresh_long_lived_token()
        except InstagramApiError as err:
            summary = str(self._friendly(err))
            self.env["omnichannel.error.log"].log(
                "provider", summary, account=account,
                code=str(err.code), technical=err.message)
            if err.retriable:
                account.last_error = summary
            else:
                account._set_error(summary)
            return False
        token = data.get("access_token")
        if not token:
            account.last_error = _("Instagram returned no new token.")
            return False
        vals = {"ig_access_token": token, "last_error": False}
        expires_in = data.get("expires_in")
        if expires_in:
            vals["ig_token_expires_at"] = fields.Datetime.now() + \
                datetime.timedelta(seconds=int(expires_in))
        account.write(vals)
        return True

    # --- errors ---
    @api.model
    def handle_provider_error(self, account, error, message=None):
        summary = self._friendly(error)
        vals = {"account": account, "code": str(getattr(error, "code", "")),
                "technical": getattr(error, "message", str(error))}
        if message is not None:
            vals["message_id"] = message.id
            vals["conversation_id"] = message.conversation_id.id
            message.write({"error_code": vals["code"],
                           "error_message": summary})
        self.env["omnichannel.error.log"].log("provider", summary, **vals)
        return summary

    @api.model
    def _friendly(self, error):
        code = getattr(error, "code", None)
        if code in FRIENDLY_ERRORS:
            return self.env._(FRIENDLY_ERRORS[code])
        return _("Instagram error: %s", getattr(error, "message", str(error)))
