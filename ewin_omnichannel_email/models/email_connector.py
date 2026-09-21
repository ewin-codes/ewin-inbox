import email
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EmailConnector(models.AbstractModel):
    _name = "omnichannel.connector.email"
    _inherit = "omnichannel.connector"
    _description = "Email Connector"

    # ---- connection ----
    @api.model
    def _require_tls(self, account):
        if account.email_smtp_security == "none":
            raise UserError(_("SMTP must use STARTTLS or SSL/TLS."))

    @api.model
    def connect(self, account):
        """Verify BOTH the inbound (IMAP) and outbound (SMTP) paths so the
        operator learns immediately if either side is misconfigured, instead of
        discovering a broken SMTP only when a reply silently fails to send."""
        from ..services.email_client import EmailClient, EmailError
        self._require_tls(account)
        client = EmailClient(account)
        errors = []
        try:
            client.connect_imap()
        except EmailError as err:
            errors.append(_("IMAP (incoming): %s", err))
        finally:
            client.logout()
        try:
            client.check_smtp()
        except EmailError as err:
            errors.append(_("SMTP (outgoing): %s", err))
        if errors:
            summary = " · ".join(errors)
            account._set_error(summary)
            return self._notify_ui(
                _("Connection check failed — %s", summary), kind="danger")
        account.sudo().write({"state": "connected", "last_error": False})
        return self._notify_ui(_("Connection OK — IMAP and SMTP both work."))

    # ---- inbound polling ----
    @api.model
    def poll_all(self):
        accounts = self.env["omnichannel.account"].search([
            ("channel_code", "=", "email"),
            ("active", "=", True),
            ("state", "!=", "disabled"),
        ])
        for account in accounts:
            try:
                self.poll_account(account)
            except Exception as err:  # noqa: BLE001 - isolate accounts
                self.env["omnichannel.error.log"].log(
                    "provider", "Email poll failed", account=account,
                    technical=str(err))
        return True

    @api.model
    def poll_account(self, account):
        from ..services.email_client import EmailClient
        if not account.email_imap_host:
            return True
        client = EmailClient(account)
        client.connect_imap()
        try:
            for uid, raw in client.fetch_unseen():
                try:
                    self._process_raw(account, raw)
                    self.env.cr.commit()
                    client.mark_seen(uid)
                except Exception as err:  # noqa: BLE001 - keep polling
                    self.env.cr.rollback()
                    self.env["omnichannel.error.log"].log(
                        "internal", "Failed to process email",
                        account=account, technical=str(err))
        finally:
            client.logout()
        return True

    @api.model
    def _process_raw(self, account, raw):
        msg = email.message_from_bytes(raw)
        normalizer = self.env["omnichannel.email.normalizer"]
        normalized = normalizer.normalize_message(account, msg)
        if not normalized:
            return self.env["omnichannel.message"]
        event, created = self.env["omnichannel.event"].record(
            account, normalized["event_id"], "message",
            normalized["raw_payload"])
        if not created and event.state in ("processed", "skipped"):
            return self.env["omnichannel.message"].search(
                [("account_id", "=", account.id),
                 ("external_message_id", "=", normalized["external_message_id"])],
                limit=1)
        try:
            message = self.env["omnichannel.routing.service"].process_event(
                account, normalized)
            self._post_process(account, message, normalized)
            event.mark_processed()
        except Exception as err:  # noqa: BLE001
            event.mark_failed(str(err))
            raise
        return message

    @api.model
    def _post_process(self, account, message, normalized):
        conv = message.conversation_id
        subject = normalized["message"].get("subject")
        # Store the subject in its own field (conv.name stays the customer,
        # like chat channels). Set it once, from the first inbound message.
        if subject and len(conv.omni_message_ids) == 1 and not conv.subject:
            conv.subject = subject[:200]
            # Surface the subject in the Discuss sidebar too, where operators
            # actually read — the mirror channel was created (with the customer
            # name) before the subject was known.
            if conv.discuss_channel_id:
                conv.discuss_channel_id.name = "%s · %s" % (
                    conv.name or account.name, subject[:120])
        partner = conv.partner_id
        addr = normalized["external_user"]["id"]
        # Only the correspondent this conversation belongs to may fill in the
        # customer's address: a threaded reply can come from any sender, and
        # writing theirs onto the customer's contact would redirect everything
        # else Odoo sends to that contact.
        if (partner and not partner.email and addr
                and message.author_partner_id == partner):
            partner.email = addr

    # ---- attachments ----
    @api.model
    def download_attachment(self, account, provider_attachment):
        if not account.email_download_files:
            return self.env["ir.attachment"]
        data = provider_attachment.get("data") or b""
        if not data:
            return self.env["ir.attachment"]
        try:
            return self.env["omnichannel.email.attachment.service"].store(
                account, data, provider_attachment.get("filename", "file"),
                provider_attachment.get("mime_type"))
        except Exception as err:  # noqa: BLE001
            self.env["omnichannel.error.log"].log(
                "attachment", "Failed to store email attachment",
                account=account, technical=str(err))
            return self.env["ir.attachment"]

    # ---- outbound ----
    @api.model
    def send_message(self, account, message):
        from email.utils import make_msgid
        from ..services.email_client import EmailClient, EmailError
        conv = message.conversation_id
        to_addr = conv.identity_id.external_id
        # The From address is the mailbox address (also the auth login). It is
        # required by a constraint, but guard defensively so a bad record fails
        # clearly instead of a cryptic smtplib error on a False address.
        from_addr = account.email_address
        if not from_addr:
            from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
                import NonRetriableError
            raise NonRetriableError(
                "This Email account has no address configured; set "
                "'Email Address' before sending.")
        from_name = account.email_from_name or account.name
        # Reply keeps the thread's Subject line (conv.subject), not conv.name
        # (which is the customer for email, same as chat channels).
        subject = conv.subject or conv.name or "(no subject)"
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        last_inbound = self.env["omnichannel.message"].search([
            ("conversation_id", "=", conv.id),
            ("direction", "=", "inbound"),
            ("external_message_id", "!=", False),
        ], order="id desc", limit=1)
        in_reply_to = last_inbound.external_message_id or None
        domain = from_addr.split("@")[-1] if "@" in from_addr else "ewin"
        message_id = make_msgid(domain=domain)
        client = EmailClient(account)
        try:
            client.send(
                from_addr=from_addr, from_name=from_name,
                to_addr=to_addr, subject=subject,
                html_body=message.body or "", message_id=message_id,
                in_reply_to=in_reply_to, references=in_reply_to,
                attachments=message.attachment_ids)
        except EmailError as err:
            self.handle_provider_error(account, err, message=message)
            if not err.retriable:
                from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
                    import NonRetriableError
                raise NonRetriableError(str(err))
            raise
        message.write({
            "state": "sent",
            "external_message_id": message_id,
            "sent_at": fields.Datetime.now(),
            "error_message": False, "error_code": False,
        })
        return True

    @api.model
    def handle_provider_error(self, account, error, message=None):
        summary = str(error)
        vals = {"account": account, "technical": summary}
        if message is not None:
            vals["message_id"] = message.id
            vals["conversation_id"] = message.conversation_id.id
            message.write({"error_message": summary})
        self.env["omnichannel.error.log"].log("provider", summary, **vals)
        return summary

    @api.model
    def _notify_ui(self, message, kind="success"):
        """A toast on the account form.

        A provider failure is reported this way and never by raising: the
        failure path records what went wrong on the account - the error
        state, ``last_error``, a journal row - and Odoo commits a request
        only when it returns successfully. Raising would roll that record
        away and leave the form looking untouched by a failure the user
        was just told about.
        """
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": message, "type": kind,
                       "sticky": kind != "success"},
        }
