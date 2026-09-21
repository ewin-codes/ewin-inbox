from odoo import fields
from odoo.tests import tagged

from .common import NotifyCase


@tagged("post_install", "-at_install")
class TestThrottle(NotifyCase):

    def test_first_claim_always_wins(self):
        self.assertFalse(self.conversation.tg_last_notified_at)
        self.assertTrue(self.conversation._tg_claim_notification(10))
        self.assertTrue(self.conversation.tg_last_notified_at)

    def test_second_claim_inside_the_window_loses(self):
        self.assertTrue(self.conversation._tg_claim_notification(10))
        self.assertFalse(self.conversation._tg_claim_notification(10))

    def test_claim_after_the_window_wins_again(self):
        self.conversation._tg_claim_notification(10)
        stale = fields.Datetime.subtract(fields.Datetime.now(), minutes=11)
        self.env.cr.execute(
            "UPDATE omnichannel_conversation SET tg_last_notified_at = %s "
            "WHERE id = %s", (stale, self.conversation.id))
        self.conversation.invalidate_recordset(["tg_last_notified_at"])
        self.assertTrue(self.conversation._tg_claim_notification(10))

    def test_zero_minutes_never_throttles(self):
        self.assertTrue(self.conversation._tg_claim_notification(0))
        self.assertTrue(self.conversation._tg_claim_notification(0))

    def test_a_lost_claim_leaves_the_timestamp_alone(self):
        self.conversation._tg_claim_notification(10)
        first = self.conversation.tg_last_notified_at
        self.conversation._tg_claim_notification(10)
        self.assertEqual(self.conversation.tg_last_notified_at, first)

    def test_claim_is_per_conversation(self):
        other = self.env["omnichannel.conversation"].create({
            "name": "Second", "account_id": self.account.id,
            "identity_id": self.identity.id})
        self.assertTrue(self.conversation._tg_claim_notification(10))
        self.assertTrue(other._tg_claim_notification(10))
