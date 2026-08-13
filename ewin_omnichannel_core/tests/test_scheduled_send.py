from datetime import timedelta
from unittest.mock import MagicMock, patch

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

    def _fake_connector(self):
        """Stand in for a channel connector.

        The core's test channel has no connector addon behind it, so a real
        delivery attempt would raise — patching the lookup keeps this suite
        independent of which connector modules happen to be installed.
        ``send_message`` marks the message sent, exactly as every real
        connector does.
        """
        connector = MagicMock()

        def send_message(account, message):
            message.write({
                "state": "sent",
                "external_message_id": "ext-1",
                "sent_at": fields.Datetime.now(),
            })
            return True

        connector.send_message.side_effect = send_message
        return connector

    def _with_connector(self, connector):
        """Patch account._get_connector for the duration of a `with` block."""
        return patch.object(
            type(self.env["omnichannel.account"]), "_get_connector",
            return_value=connector)

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
        original_scheduled_at = message.scheduled_at
        original_scheduled_by = message.scheduled_by
        message.write({"state": "sent"})
        # Verify the scheduling metadata survives delivery
        self.assertEqual(message.scheduled_at, original_scheduled_at)
        self.assertEqual(message.scheduled_by, original_scheduled_by)
        # Verify the send time cannot be changed once sent
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

    def test_create_with_past_scheduled_at_refused(self):
        with self.assertRaises(UserError):
            self.env["omnichannel.message"].create({
                "conversation_id": self.conv.id,
                "direction": "outbound",
                "sender_type": "operator",
                "message_type": "text",
                "body": "<p>later</p>",
                "state": "scheduled",
                "scheduled_at": fields.Datetime.now() - timedelta(minutes=1),
                "scheduled_by": self.env.uid,
            })

    def test_scheduling_delivers_nothing(self):
        connector = self._fake_connector()
        with self._with_connector(connector):
            message = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "<p>see you tomorrow</p>",
                scheduled_at=self._later())
        connector.send_message.assert_not_called()
        self.assertEqual(message.state, "scheduled")
        self.assertEqual(message.scheduled_by, self.env.user)
        self.assertFalse(self.env["omnichannel.job"].search(
            [("method", "=", "send_outbound")]))

    def test_scheduling_leaves_thread_and_metrics_untouched(self):
        with self._with_connector(self._fake_connector()):
            message = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "<p>see you tomorrow</p>",
                scheduled_at=self._later())
        # not in the customer-facing thread: it keeps showing what the customer
        # has actually seen
        self.assertFalse(message.mail_message_id)
        self.assertFalse(self.conv.discuss_channel_id.message_ids)
        # and not counted as an answer: response time must span up to the real
        # delivery, not up to the moment it was planned
        self.assertFalse(self.conv.first_operator_message_at)
        self.assertFalse(self.conv.last_message_at)

    def test_scheduling_takes_the_conversation(self):
        self.assertFalse(self.conv.operator_id)
        with self._with_connector(self._fake_connector()):
            self.env["omnichannel.message.service"].create_outbound(
                self.conv, "<p>see you tomorrow</p>",
                scheduled_at=self._later())
        self.assertEqual(self.conv.operator_id, self.env.user)

    def test_internal_note_cannot_be_scheduled(self):
        with self.assertRaises(UserError):
            self.env["omnichannel.message.service"].create_outbound(
                self.conv, "<p>remind me</p>", is_internal=True,
                scheduled_at=self._later())
