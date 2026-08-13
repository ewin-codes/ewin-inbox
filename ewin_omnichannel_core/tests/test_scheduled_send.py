from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestScheduledSend(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create({
            "name": "Test Account", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create({
            "account_id": self.account.id, "external_id": "cust-1"})
        self.conv = self.env["omnichannel.conversation"].create({
            "name": "Scheduled test", "account_id": self.account.id,
            "identity_id": self.identity.id})

    def _later(self, hours=1):
        return fields.Datetime.now() + timedelta(hours=hours)

    def _scheduled_message(self, when=None):
        """A scheduled row written directly, with no service involved — what is
        under test here is the model's own guard, not the way in."""
        return self.env["omnichannel.message"].create({
            "conversation_id": self.conv.id,
            "direction": "outbound",
            "sender_type": "operator",
            "message_type": "text",
            "body": "<p>later</p>",
            "state": "scheduled",
            "scheduled_at": when or self._later(),
            "scheduled_by": self.env.uid,
        })

    def test_reschedule_while_waiting(self):
        message = self._scheduled_message()
        new_time = self._later(5)
        message.write({"scheduled_at": new_time})
        self.assertEqual(message.scheduled_at, new_time)

    def test_reschedule_into_the_past_refused(self):
        message = self._scheduled_message()
        with self.assertRaises(UserError):
            message.write(
                {"scheduled_at": fields.Datetime.now() - timedelta(minutes=1)})

    def test_send_time_frozen_once_it_has_left(self):
        message = self._scheduled_message()
        message.write({"state": "sent"})
        with self.assertRaises(UserError):
            message.write({"scheduled_at": self._later(2)})

    def test_scheduled_state_requires_a_time(self):
        with self.assertRaises(ValidationError):
            self.env["omnichannel.message"].create({
                "conversation_id": self.conv.id,
                "direction": "outbound",
                "sender_type": "operator",
                "message_type": "text",
                "state": "scheduled",
            })
