from odoo import api, fields, models


class OmnichannelAccount(models.Model):
    _inherit = "omnichannel.account"

    tg_bot_token = fields.Char(
        string="Bot Token", groups="ewin_omnichannel_core.group_omni_admin",
        copy=False)
    tg_bot_token_masked = fields.Char(
        string="Telegram Token", compute="_compute_tg_bot_token_masked")
    tg_bot_username = fields.Char(string="Bot Username")
    tg_bot_external_id = fields.Char(string="Telegram Bot ID")
    tg_webhook_secret = fields.Char(
        string="Webhook Secret", groups="ewin_omnichannel_core.group_omni_admin",
        copy=False)
    tg_webhook_status = fields.Char(
        string="Telegram Webhook Status", readonly=True)
    tg_api_base_url = fields.Char(
        string="Telegram API Base URL", default="https://api.telegram.org")
    tg_download_files = fields.Boolean(
        string="Telegram Download Files", default=True)
    tg_max_file_size = fields.Integer(
        string="Telegram Max File Size (MB)", default=20)
    tg_welcome_message = fields.Text(string="Telegram Welcome Message")
    tg_create_contacts = fields.Boolean(
        string="Telegram Auto-create Contacts", default=True)

    @api.depends("tg_bot_token")
    def _compute_tg_bot_token_masked(self):
        for acc in self:
            acc.tg_bot_token_masked = "***************" if acc.tg_bot_token else ""

    def _tg_sync_config(self):
        """Mirror create_contacts flag into the universal connector_config."""
        for acc in self:
            if acc.channel_code != "telegram":
                continue
            cfg = dict(acc.connector_config or {})
            cfg["create_contacts"] = acc.tg_create_contacts
            acc.connector_config = cfg

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._tg_sync_config()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "tg_create_contacts" in vals:
            self._tg_sync_config()
        return res

    def action_tg_check_connection(self):
        return self._get_connector().connect(self)

    def action_tg_register_webhook(self):
        return self._get_connector().register_webhook(self)

    def action_tg_remove_webhook(self):
        return self._get_connector().remove_webhook(self)

    def action_tg_webhook_info(self):
        return self._get_connector().tg_webhook_info(self)

    def action_tg_send_test(self):
        return self._get_connector().tg_send_test(self)
