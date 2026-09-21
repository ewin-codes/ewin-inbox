import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class OmnichannelMessage(models.Model):
    _inherit = "omnichannel.message"

    @api.model_create_multi
    def create(self, vals_list):
        """Notify Telegram about a customer message, once, as it is recorded.

        The hook sits on ``create`` rather than on
        ``message_service.create_inbound`` for one reason: that service
        returns the row it already has when a provider redelivers an update,
        and an override could not tell "created" from "found" without
        repeating its deduplication query. A row is born once.
        """
        messages = super().create(vals_list)
        service = self.env["omnichannel.telegram.notification.service"]
        for message in messages:
            if message.direction != "inbound" or message.sender_type != "customer":
                continue
            try:
                # The savepoint is what makes the promise below hold for a
                # database error, not just a Python one: a psycopg2.Error
                # (e.g. a serialization failure) leaves PostgreSQL in an
                # aborted-transaction state, and swallowing it without first
                # rolling back to a savepoint would poison the cursor —
                # the channel's own webhook would then fail its very next
                # query with "current transaction is aborted", losing the
                # customer's message the guard exists to protect. Rolling
                # back to the savepoint also undoes the throttle claim
                # schedule() may have already taken, so a failed enqueue
                # does not leave the conversation silent until the window
                # expires.
                with self.env.cr.savepoint():
                    service.schedule(message)
            except Exception:  # noqa: BLE001
                # This runs inside the channel's webhook transaction. An
                # add-on has no right to cost the customer their message —
                # acceptance criterion 4 says so in as many words.
                _logger.exception(
                    "Telegram notification not scheduled for message %s",
                    message.id)
        return messages
