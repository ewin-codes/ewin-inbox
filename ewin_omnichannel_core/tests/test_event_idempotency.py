from odoo.tests import tagged

from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestEventIdempotency(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})

    def test_record_creates_once(self):
        Event = self.env["omnichannel.event"]
        ev1, created1 = Event.record(self.account, "test:update:1", "message")
        ev2, created2 = Event.record(self.account, "test:update:1", "message")
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(ev1, ev2)
        self.assertEqual(Event.search_count(
            [("account_id", "=", self.account.id)]), 1)
