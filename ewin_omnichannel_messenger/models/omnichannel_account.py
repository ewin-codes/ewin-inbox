import uuid

from odoo import api, fields, models


class OmnichannelAccount(models.Model):
    _inherit = "omnichannel.account"

    mg_page_id = fields.Char(
        string="Page ID",
        help="Numeric Page ID (shown under the Page name in Meta). Optional: "
             "the Page access token is already page-scoped, so sending and "
             "receiving work without it. If set, inbound webhooks are checked "
             "against it; if left blank it is learned automatically from the "
             "first event.")
    mg_page_name = fields.Char(string="Page Name", readonly=True)
    mg_page_access_token = fields.Char(
        string="Page Access Token",
        groups="ewin_omnichannel_core.group_omni_admin", copy=False,
        help="The 'Access token' (RU: «Маркер доступа») generated for your "
             "Page in Meta → Messenger → Settings. Prefer a permanent System "
             "User token for production.")
    mg_webhook_url = fields.Char(
        string="Messenger Webhook Callback URL",
        compute="_compute_mg_webhook_url",
        help="Paste this into Meta → Messenger → Settings → Webhooks as the "
             "Callback URL.")
    mg_page_access_token_masked = fields.Char(
        string="Messenger Token", compute="_compute_mg_token_masked")
    mg_app_secret = fields.Char(
        string="Messenger App Secret",
        groups="ewin_omnichannel_core.group_omni_admin", copy=False,
        help="Meta → App Settings → Basic → App Secret. Required: inbound "
             "webhooks are rejected unless their signature matches it.")
    mg_verify_token = fields.Char(
        string="Messenger Webhook Verify Token",
        groups="ewin_omnichannel_core.group_omni_admin", copy=False,
        help="Generated automatically. Paste it into Meta → Webhooks as the "
             "Verify Token — you do not invent this value.")
    mg_graph_version = fields.Char(
        string="Messenger Graph API Version", default="v21.0")
    mg_download_files = fields.Boolean(
        string="Messenger Download Files", default=True)
    mg_max_file_size = fields.Integer(
        string="Messenger Max File Size (MB)", default=25)
    mg_create_contacts = fields.Boolean(
        string="Messenger Auto-create Contacts", default=True)
    mg_fetch_profile = fields.Boolean(
        string="Messenger Fetch User Profiles", default=True,
        help="Look up the customer's name and picture via the Graph profile "
             "API when a new conversation starts.")

    @api.depends("mg_page_access_token")
    def _compute_mg_token_masked(self):
        for acc in self:
            acc.mg_page_access_token_masked = "***************" \
                if acc.mg_page_access_token else ""

    @api.depends("webhook_uuid", "channel_code")
    def _compute_mg_webhook_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url") or ""
        for acc in self:
            acc.mg_webhook_url = (
                f"{base}/omnichannel/webhook/messenger/{acc.webhook_uuid}"
                if acc.channel_code == "messenger" and acc.webhook_uuid else "")

    def _mg_sync_config(self):
        for acc in self:
            if acc.channel_code != "messenger":
                continue
            cfg = dict(acc.connector_config or {})
            cfg["create_contacts"] = acc.mg_create_contacts
            acc.connector_config = cfg

    def _mg_ensure_verify_token(self):
        for acc in self:
            if acc.channel_code == "messenger" and not acc.sudo().mg_verify_token:
                acc.sudo().mg_verify_token = uuid.uuid4().hex

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._mg_sync_config()
        records._mg_ensure_verify_token()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "mg_create_contacts" in vals:
            self._mg_sync_config()
        return res

    def action_mg_check_connection(self):
        return self._get_connector().connect(self)
