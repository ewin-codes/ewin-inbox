import datetime
import uuid

from odoo import _, api, fields, models

# How long before expiry the daily cron refreshes a token. The 60-day lead-in
# comfortably clears Instagram's "token must be >24h old to refresh" rule.
_IG_REFRESH_LEAD = datetime.timedelta(days=10)
# Lifetime of a freshly minted Instagram long-lived token, used to seed
# ig_token_expires_at when a token is pasted (its exact expiry is not returned
# at paste time; the refresh endpoint reports the precise value thereafter).
_IG_TOKEN_LIFETIME = datetime.timedelta(days=60)


class OmnichannelAccount(models.Model):
    _inherit = "omnichannel.account"

    ig_user_id = fields.Char(
        string="Instagram Account ID",
        help="Numeric Instagram account ID. Optional: the token is already "
             "account-scoped, so sending and receiving work without it. If "
             "set, inbound webhooks are checked against it; if left blank it "
             "is learned automatically from Check Connection or the first "
             "event.")
    ig_username = fields.Char(string="Username", readonly=True)
    ig_access_token = fields.Char(
        string="Instagram Access Token",
        groups="ewin_omnichannel_core.group_omni_admin", copy=False,
        help="The long-lived Instagram access token generated in Meta → your "
             "app → Instagram → API setup with Instagram business login → "
             "Generate token. It is auto-refreshed before it expires.")
    ig_token_expires_at = fields.Datetime(
        string="Token Expires", readonly=True,
        help="When the current access token expires. Refreshed automatically "
             "by a daily job ahead of this date.")
    ig_webhook_url = fields.Char(
        string="Instagram Webhook Callback URL",
        compute="_compute_ig_webhook_url",
        help="Paste this into Meta → your app → Instagram → Webhooks as the "
             "Callback URL.")
    ig_access_token_masked = fields.Char(
        string="Instagram Token", compute="_compute_ig_token_masked")
    ig_app_secret = fields.Char(
        string="Instagram App Secret",
        groups="ewin_omnichannel_core.group_omni_admin", copy=False,
        help="Meta → App settings → Basic → App Secret. Required: inbound "
             "webhooks are rejected unless their signature matches it.")
    ig_verify_token = fields.Char(
        string="Instagram Webhook Verify Token",
        groups="ewin_omnichannel_core.group_omni_admin", copy=False,
        help="Generated automatically. Paste it into Meta → Webhooks as the "
             "Verify Token — you do not invent this value.")
    ig_graph_version = fields.Char(
        string="Instagram Graph API Version", default="v21.0")
    ig_download_files = fields.Boolean(
        string="Instagram Download Files", default=True)
    ig_max_file_size = fields.Integer(
        string="Instagram Max File Size (MB)", default=25)
    ig_create_contacts = fields.Boolean(
        string="Instagram Auto-create Contacts", default=True)
    ig_fetch_profile = fields.Boolean(
        string="Instagram Fetch User Profiles", default=True,
        help="Look up the customer's name, @username and picture via the Graph "
             "profile API when a new conversation starts.")
    ig_human_agent = fields.Boolean(
        string="Human Agent Tag",
        help="When on, replies sent after the 24-hour window use the "
             "HUMAN_AGENT tag, which extends the window to 7 days. Requires "
             "Meta's Human Agent feature approved for your app; leave off "
             "otherwise, or messages outside the window are rejected.")

    @api.depends("ig_access_token")
    def _compute_ig_token_masked(self):
        for acc in self:
            # sudo(): the credential is admin-only, and this compute backs
            # the field the operator group sees in its place on the same
            # form. Without it, opening the account form as an operator
            # raises AccessError from the very field that exists so they
            # never see the credential. Deriving a fixed-length mask is not
            # the access the connector's _client() guards.
            acc.ig_access_token_masked = (
                "***************" if acc.sudo().ig_access_token else "")

    @api.depends("webhook_uuid", "channel_code")
    def _compute_ig_webhook_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url") or ""
        for acc in self:
            acc.ig_webhook_url = (
                f"{base}/omnichannel/webhook/instagram/{acc.webhook_uuid}"
                if acc.channel_code == "instagram" and acc.webhook_uuid else "")

    def _ig_sync_config(self):
        for acc in self:
            if acc.channel_code != "instagram":
                continue
            cfg = dict(acc.connector_config or {})
            cfg["create_contacts"] = acc.ig_create_contacts
            acc.connector_config = cfg

    def _ig_ensure_verify_token(self):
        for acc in self:
            if acc.channel_code == "instagram" and not acc.sudo().ig_verify_token:
                acc.sudo().ig_verify_token = uuid.uuid4().hex

    @api.model
    def _ig_seed_expiry(self, vals):
        """A freshly pasted token gets a 60-day expiry so the refresh cron can
        take over its lifecycle. An explicit expiry in the same write (set by
        the refresh flow) is left untouched."""
        if vals.get("ig_access_token") and "ig_token_expires_at" not in vals:
            return {**vals, "ig_token_expires_at":
                    fields.Datetime.now() + _IG_TOKEN_LIFETIME}
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._ig_seed_expiry(v) for v in vals_list]
        records = super().create(vals_list)
        records._ig_sync_config()
        records._ig_ensure_verify_token()
        return records

    def write(self, vals):
        vals = self._ig_seed_expiry(vals)
        res = super().write(vals)
        if "ig_create_contacts" in vals:
            self._ig_sync_config()
        return res

    def _get_public_address(self):
        self.ensure_one()
        if self.channel_code != "instagram":
            return super()._get_public_address()
        username = (self.sudo().ig_username or "").lstrip("@")
        return f"@{username}" if username else ""

    def action_ig_check_connection(self):
        return self._run_connector_action("connect")

    def action_ig_refresh_token(self):
        connector = self.env["omnichannel.connector.instagram"]
        if self._run_connector_action("refresh_token"):
            return connector._notify_ui(_("Access token refreshed."))
        # refresh_token wrote the reason on the account rather than raising
        # it, so that both the journal row and the error state survive this
        # request. Read it back instead of restating it here.
        return connector._notify_ui(
            self.sudo().last_error or _("Instagram refused the refresh."),
            kind="danger")

    @api.model
    def _cron_ig_refresh_tokens(self):
        """Refresh Instagram tokens approaching expiry (daily). Each account is
        handled independently so one failure never blocks the others."""
        deadline = fields.Datetime.now() + _IG_REFRESH_LEAD
        accounts = self.sudo().search([
            ("channel_code", "=", "instagram"),
            ("active", "=", True),
            ("state", "!=", "disabled"),
            ("ig_access_token", "!=", False),
            "|", ("ig_token_expires_at", "=", False),
            ("ig_token_expires_at", "<=", deadline),
        ])
        connector = self.env["omnichannel.connector.instagram"]
        for account in accounts:
            connector.refresh_token(account)
        return True
