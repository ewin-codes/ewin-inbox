from odoo import api, fields, models


class OmnichannelAccount(models.Model):
    _inherit = "omnichannel.account"

    viber_auth_token = fields.Char(
        string="Auth Token", groups="ewin_omnichannel_core.group_omni_admin",
        copy=False)
    viber_auth_token_masked = fields.Char(
        string="Viber Token", compute="_compute_viber_auth_token_masked")
    viber_bot_name = fields.Char(
        string="Bot Name",
        help="Sender name shown to the customer (max 28 chars). "
             "Filled automatically on 'Check Connection'.")
    viber_bot_uri = fields.Char(string="Bot URI", readonly=True)
    viber_bot_id = fields.Char(string="Viber Bot ID", readonly=True)
    viber_webhook_status = fields.Char(
        string="Viber Webhook Status", readonly=True)
    viber_api_base_url = fields.Char(
        string="Viber API Base URL", default="https://chatapi.viber.com/pa")
    viber_download_files = fields.Boolean(
        string="Viber Download Files", default=True)
    viber_max_file_size = fields.Integer(
        string="Viber Max File Size (MB)", default=50)
    viber_create_contacts = fields.Boolean(
        string="Viber Auto-create Contacts", default=True)

    @api.depends("viber_auth_token")
    def _compute_viber_auth_token_masked(self):
        for acc in self:
            # sudo(): the credential is admin-only, and this compute backs
            # the field the operator group sees in its place on the same
            # form. Without it, opening the account form as an operator
            # raises AccessError from the very field that exists so they
            # never see the credential. Deriving a fixed-length mask is not
            # the access the connector's _client() guards.
            acc.viber_auth_token_masked = (
                "***************" if acc.sudo().viber_auth_token else "")

    def _viber_sync_config(self):
        """Mirror create_contacts flag into the universal connector_config."""
        for acc in self:
            if acc.channel_code != "viber":
                continue
            cfg = dict(acc.connector_config or {})
            cfg["create_contacts"] = acc.viber_create_contacts
            acc.connector_config = cfg

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._viber_sync_config()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "viber_create_contacts" in vals:
            self._viber_sync_config()
        return res

    def _get_public_address(self):
        self.ensure_one()
        if self.channel_code != "viber":
            return super()._get_public_address()
        return self.sudo().viber_bot_name or ""

    def action_viber_check_connection(self):
        return self._run_connector_action("connect")

    def action_viber_register_webhook(self):
        return self._run_connector_action("register_webhook")

    def action_viber_remove_webhook(self):
        return self._run_connector_action("remove_webhook")

    def action_viber_webhook_info(self):
        return self._run_connector_action("viber_webhook_info")
