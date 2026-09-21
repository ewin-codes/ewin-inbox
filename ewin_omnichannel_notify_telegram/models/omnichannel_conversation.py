from odoo import fields, models


class OmnichannelConversation(models.Model):
    _inherit = "omnichannel.conversation"

    tg_last_notified_at = fields.Datetime(
        string="Last Telegram Notification", readonly=True, copy=False,
        help="When this conversation last produced a Telegram notification. "
             "Empty on a new conversation, which is why the first message "
             "always notifies.")

    def _tg_claim_notification(self, throttle_minutes):
        """Win, exactly once, the right to notify about this conversation.

        Reading the timestamp and writing it back cannot do this. Two inbound
        messages landing in the same second reach different workers, both read
        the same value, and both decide to notify. One conditional UPDATE lets
        PostgreSQL settle it: the transaction that gets a row back may notify,
        the other gets nothing and leaves quietly. The same device
        ``message_service.release_scheduled`` uses, for the same reason.

        A window of zero minutes never throttles: the cutoff is then ``now``
        and any stored timestamp is at or before it.
        """
        self.ensure_one()
        # Flush first: a pending ORM write to this column would otherwise be
        # flushed after the raw UPDATE and overwrite what it just decided.
        self.flush_recordset(["tg_last_notified_at"])
        now = fields.Datetime.now()
        cutoff = fields.Datetime.subtract(now, minutes=throttle_minutes)
        self.env.cr.execute("""
            UPDATE omnichannel_conversation SET tg_last_notified_at = %s
             WHERE id = %s
               AND (tg_last_notified_at IS NULL OR tg_last_notified_at <= %s)
         RETURNING id
        """, (now, self.id, cutoff))
        claimed = bool(self.env.cr.fetchone())
        if claimed:
            # The UPDATE went behind the ORM's back; drop the stale cache.
            self.invalidate_recordset(["tg_last_notified_at"])
        return claimed
