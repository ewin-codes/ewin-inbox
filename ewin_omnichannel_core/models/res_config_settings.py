from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    omni_send_shortcut = fields.Selection(
        [("ctrl_enter", "Ctrl + Enter"), ("enter", "Enter")],
        string="Send message with",
        default="ctrl_enter",
        config_parameter="ewin_omnichannel.send_shortcut",
        help="Keyboard shortcut that sends the reply from the composer. "
             "Enter always inserts a newline when Ctrl+Enter is selected.")
