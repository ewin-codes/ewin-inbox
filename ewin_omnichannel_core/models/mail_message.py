from odoo import fields, models


class MailMessage(models.Model):
    _inherit = "mail.message"

    # The other end of omnichannel.message.history_message_ids. Declared so a
    # backfill can hand the ledger row to the same batched create that writes
    # the copies: linking afterwards would cost one statement per message, and
    # the whole point of batching there is that a conversation can be hundreds
    # of messages long.
    omni_message_ids = fields.Many2many(
        "omnichannel.message", "omni_message_history_rel",
        "mail_message_id", "omni_message_id", string="Mirrored Messages",
        copy=False,
        help="The conversation messages this chatter entry is a copy of.")
