from odoo import api, fields, models
from odoo.exceptions import ValidationError


class OmnichannelAccount(models.Model):
    _inherit = "omnichannel.account"

    email_address = fields.Char(string="Email Address", copy=False)
    email_from_name = fields.Char(
        string="Sender Name",
        help="Display name the customer sees as the email sender "
             "(e.g. 'BenidormHomes Support'). Defaults to the account name.")
    email_password = fields.Char(
        string="Password", groups="ewin_omnichannel_core.group_omni_admin",
        copy=False)
    email_password_masked = fields.Char(
        string="Password (masked)", compute="_compute_email_password_masked")
    email_imap_host = fields.Char(string="IMAP Host")
    email_imap_port = fields.Integer(string="IMAP Port", default=993)
    email_imap_ssl = fields.Boolean(string="IMAP SSL", default=True)
    email_smtp_host = fields.Char(string="SMTP Host")
    email_smtp_port = fields.Integer(string="SMTP Port", default=587)
    email_smtp_security = fields.Selection(
        [("none", "None"), ("starttls", "STARTTLS"), ("ssl", "SSL/TLS")],
        string="SMTP Security", default="starttls")
    email_folder = fields.Char(string="Mailbox Folder", default="INBOX")
    email_download_files = fields.Boolean(
        string="Email Download Files", default=True)
    email_max_file_size = fields.Integer(
        string="Email Max File Size (MB)", default=25)
    email_create_contacts = fields.Boolean(
        string="Email Auto-create Contacts", default=True)

    @api.depends("email_password")
    def _compute_email_password_masked(self):
        for acc in self:
            # sudo(): the credential is admin-only, and this compute backs
            # the field the operator group sees in its place on the same
            # form. Without it, opening the account form as an operator
            # raises AccessError from the very field that exists so they
            # never see the credential. Deriving a fixed-length mask is not
            # the access the connector's _client() guards.
            acc.email_password_masked = (
                "***************" if acc.sudo().email_password else "")

    def _email_sync_config(self):
        for acc in self:
            if acc.channel_code != "email":
                continue
            cfg = dict(acc.connector_config or {})
            cfg["create_contacts"] = acc.email_create_contacts
            acc.connector_config = cfg

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._email_sync_config()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "email_create_contacts" in vals:
            self._email_sync_config()
        return res

    @api.constrains("email_smtp_security", "channel_code")
    def _check_email_smtp_tls(self):
        for acc in self:
            if acc.channel_code == "email" and acc.email_smtp_security == "none":
                raise ValidationError(
                    "SMTP must use STARTTLS or SSL/TLS — plaintext auth is not "
                    "allowed.")

    @api.constrains("email_address", "channel_code")
    def _check_email_address(self):
        for acc in self:
            if acc.channel_code == "email" and not acc.email_address:
                raise ValidationError(
                    "Email Address is required for an email account (it is the "
                    "mailbox login and the From address).")

    def action_email_check_connection(self):
        return self._run_connector_action("connect")

    def action_email_fetch_now(self):
        self._run_connector_action("poll_account")
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": "Mailbox polled.", "type": "success",
                       "sticky": False},
        }
