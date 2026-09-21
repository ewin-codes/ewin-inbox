from odoo import fields, models


class OmnichannelTelegramLink(models.TransientModel):
    _name = "omnichannel.telegram.link"
    _description = "Telegram Linking Link"

    user_id = fields.Many2one("res.users", required=True, readonly=True)
    bot_username = fields.Char(readonly=True)
    url = fields.Char(string="Your personal link", readonly=True)
