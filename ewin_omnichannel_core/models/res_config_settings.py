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

    omni_close_reason_policy = fields.Selection(
        [("off", "Do not ask"),
         ("optional", "Ask, may be skipped"),
         ("required", "Ask, an answer is required")],
        string="Closing reason",
        default="off",
        config_parameter="ewin_omnichannel.close_reason_policy",
        help="Whether closing a conversation asks the operator why. When an "
             "answer is required, a conversation stays open until one is "
             "given. The preset answers live under Close Reasons.")
