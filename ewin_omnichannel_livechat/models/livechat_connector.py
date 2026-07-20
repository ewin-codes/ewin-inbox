import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LivechatConnector(models.AbstractModel):
    _name = "omnichannel.connector.livechat"
    _inherit = "omnichannel.connector"
    _description = "Live Chat Connector"

    # -- configuration / lifecycle -------------------------------------
    @api.model
    def validate_configuration(self, account):
        if not account.livechat_channel_id:
            raise UserError(_("Set the Live Chat channel to bridge."))
        bridge = account.livechat_bridge_user_id
        if not bridge:
            raise UserError(_("Set the bridge operator user."))
        if bridge not in account.livechat_channel_id.user_ids:
            raise UserError(_(
                "The bridge operator must be an operator of the "
                "Live Chat channel '%s'.", account.livechat_channel_id.name))
        return True

    @api.model
    def connect(self, account):
        self.validate_configuration(account)
        account._livechat_ensure_bridge_presence()
        account.sudo().write({"state": "connected", "last_error": False})
        return self._notify_ui(_("Live Chat bridge connected."))

    @api.model
    def disconnect(self, account):
        account.sudo().write({"state": "disabled"})
        return True

    # internal channel: no external webhook
    @api.model
    def register_webhook(self, account):
        return True

    @api.model
    def remove_webhook(self, account):
        return True

    @api.model
    def parse_webhook(self, account, payload, headers):
        return True

    @api.model
    def _notify_ui(self, message):
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": message, "type": "success", "sticky": False},
        }
