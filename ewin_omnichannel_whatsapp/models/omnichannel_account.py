import uuid

from odoo import api, fields, models


class OmnichannelAccount(models.Model):
    _inherit = "omnichannel.account"

    wa_access_token = fields.Char(
        string="WhatsApp Access Token",
        groups="ewin_omnichannel_core.group_omni_admin", copy=False)
    wa_access_token_masked = fields.Char(
        string="WhatsApp Token", compute="_compute_wa_access_token_masked")
    wa_phone_number_id = fields.Char(string="Phone Number ID")
    wa_waba_id = fields.Char(string="WhatsApp Business Account ID")
    wa_business_phone = fields.Char(string="Business Phone", readonly=True)
    wa_app_secret = fields.Char(
        string="WhatsApp App Secret",
        groups="ewin_omnichannel_core.group_omni_admin", copy=False)
    wa_verify_token = fields.Char(
        string="WhatsApp Webhook Verify Token",
        groups="ewin_omnichannel_core.group_omni_admin", copy=False)
    wa_graph_version = fields.Char(
        string="WhatsApp Graph API Version", default="v21.0")
    wa_download_files = fields.Boolean(
        string="WhatsApp Download Files", default=True)
    wa_max_file_size = fields.Integer(
        string="WhatsApp Max File Size (MB)", default=25)
    wa_create_contacts = fields.Boolean(
        string="WhatsApp Auto-create Contacts", default=True)

    @api.depends("wa_access_token")
    def _compute_wa_access_token_masked(self):
        for acc in self:
            acc.wa_access_token_masked = "***************" \
                if acc.wa_access_token else ""

    def _wa_sync_config(self):
        for acc in self:
            if acc.channel_code != "whatsapp":
                continue
            cfg = dict(acc.connector_config or {})
            cfg["create_contacts"] = acc.wa_create_contacts
            acc.connector_config = cfg

    def _wa_ensure_verify_token(self):
        for acc in self:
            if acc.channel_code == "whatsapp" and not acc.sudo().wa_verify_token:
                acc.sudo().wa_verify_token = uuid.uuid4().hex

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._wa_sync_config()
        records._wa_ensure_verify_token()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "wa_create_contacts" in vals:
            self._wa_sync_config()
        return res

    def action_wa_check_connection(self):
        return self._get_connector().connect(self)

    def action_wa_sync_templates(self):
        return self._get_connector().sync_templates(self)
