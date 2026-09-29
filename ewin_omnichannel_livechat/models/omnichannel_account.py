from odoo import api, fields, models


class OmnichannelAccount(models.Model):
    _inherit = "omnichannel.account"

    livechat_channel_id = fields.Many2one(
        "im_livechat.channel", string="Live Chat Channel",
        help="The Odoo Live Chat channel bridged into this account.")
    livechat_bridge_user_id = fields.Many2one(
        "res.users", string="Bridge Operator",
        help="Technical operator that keeps livechat sessions open. EWIN owns "
             "the real routing; this user does no human work.")

    def _get_public_address(self):
        self.ensure_one()
        if self.channel_code != "livechat":
            return super()._get_public_address()
        return self.sudo().livechat_channel_id.name or ""

    def action_livechat_check_connection(self):
        return self._run_connector_action("connect")

    @api.model
    def _livechat_find_for_channel(self, livechat_channel):
        """Return the bridging account for a given im_livechat.channel."""
        if not livechat_channel:
            return self.browse()
        return self.sudo().search([
            ("channel_code", "=", "livechat"),
            ("livechat_channel_id", "=", livechat_channel.id),
            ("state", "!=", "disabled"),
        ], limit=1)

    def _livechat_ensure_bridge_presence(self):
        """Pin the bridge user's bus.presence to online so im_livechat treats
        it as an available operator."""
        Presence = self.env["bus.presence"].sudo()
        now = fields.Datetime.now()
        for account in self.filtered("livechat_bridge_user_id"):
            user = account.livechat_bridge_user_id
            vals = {"status": "online", "last_poll": now, "last_presence": now}
            presence = Presence.search([("user_id", "=", user.id)], limit=1)
            if presence:
                presence.write(vals)
            else:
                Presence.create({"user_id": user.id, **vals})

    @api.model
    def _cron_livechat_bridge_presence(self):
        self.search([
            ("channel_code", "=", "livechat"),
            ("state", "=", "connected"),
        ])._livechat_ensure_bridge_presence()
