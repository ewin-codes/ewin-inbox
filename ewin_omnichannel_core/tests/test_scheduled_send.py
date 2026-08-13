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

    def _schedule(self, when=None, body="<p>see you tomorrow</p>"):
        """Schedule a reply the way the composer does."""
        with self._with_connector(self._fake_connector()):
            return self.env["omnichannel.message.service"].create_outbound(
                self.conv, body, scheduled_at=when or self._later())

    def test_release_delivers_and_mirrors(self):
        message = self._schedule()
        connector = self._fake_connector()
        with self._with_connector(connector):
            self.env["omnichannel.message.service"].release_scheduled(message)
        connector.send_message.assert_called_once()
        self.assertEqual(message.state, "sent")
        # now it belongs in the thread and on the conversation's clock
        self.assertTrue(message.mail_message_id)
        self.assertTrue(self.conv.first_operator_message_at)
        self.assertTrue(self.conv.last_message_at)

    def test_release_is_idempotent(self):
        message = self._schedule()
        connector = self._fake_connector()
        with self._with_connector(connector):
            service = self.env["omnichannel.message.service"]
            service.release_scheduled(message)
            service.release_scheduled(message)
        self.assertEqual(connector.send_message.call_count, 1)
        # exactly one post in the mirror channel: a second release would post
        # again and simply move mail_message_id, so counting the channel is
        # what actually proves it, not looking the id up.
        self.assertEqual(len(self.conv.discuss_channel_id.message_ids), 1)

    def test_release_reopens_a_closed_conversation(self):
        message = self._schedule()
        self.conv._close()
        self.assertEqual(self.conv.state, "closed")
        with self._with_connector(self._fake_connector()):
            self.env["omnichannel.message.service"].release_scheduled(message)
        self.assertEqual(self.conv.state, "open")
        self.assertEqual(message.state, "sent")

    def test_response_time_is_measured_at_delivery(self):
        self.conv.write({
            "first_customer_message_at": fields.Datetime.now() - timedelta(hours=2)})
        message = self._schedule()
        # planning alone must not stop the clock
        self.assertEqual(self.conv.first_response_seconds, 0)
        with self._with_connector(self._fake_connector()):
            self.env["omnichannel.message.service"].release_scheduled(message)
        self.assertGreaterEqual(self.conv.first_response_seconds, 7200)

    def test_release_is_guarded_at_database_level(self):
        """The database guard reads the committed row, not the ORM cache.

        A concurrent caller can pass an ORM-based check against a stale cache:
        the row locked and updated by another transaction, while the local cache
        still says the old value. The SQL WHERE clause re-evaluated after the
        lock is granted catches this, refusing to update a row that no longer
        matches the condition. This test proves the guard works at the database
        level, not the cache level, by simulating the stale-cache scenario: the
        row is moved out from under the cached state without invalidating the
        cache, then a release is called and correctly refuses to send.
        """
        message = self._schedule()
        # The Python cache now holds: state = "scheduled"
        self.assertEqual(message.state, "scheduled")
        # Move the row out from under that cache — raw SQL, do not touch ORM.
        # This simulates what another transaction does while we hold the stale
        # cache: it moves the row to sent.
        self.env.cr.execute(
            "UPDATE omnichannel_message SET state = %s WHERE id = %s",
            ("sent", message.id))
        # The Python cache still says "scheduled" — that is the whole point.
        # If the guard were cache-based, release_scheduled would proceed.
        # If the guard is database-based, it will refuse.
        connector = self._fake_connector()
        with self._with_connector(connector):
            self.env["omnichannel.message.service"].release_scheduled(message)
        # The connector was never called: the WHERE state = 'scheduled' matched
        # no row, so release_scheduled bailed out without reaching delivery.
        self.assertEqual(connector.send_message.call_count, 0)
        # No post in the mirror channel: release never ran the finalize sequence.
        self.assertEqual(len(self.conv.discuss_channel_id.message_ids), 0)

    def test_cron_releases_a_due_message(self):
        message = self._schedule(self._later(1))
        connector = self._fake_connector()
        due = fields.Datetime.now() + timedelta(hours=2)
        with patch.object(fields.Datetime, "now", return_value=due), \
             self._with_connector(connector):
            self.env["omnichannel.message"]._cron_send_scheduled()
        connector.send_message.assert_called_once()
        self.assertEqual(message.state, "sent")

    def test_cron_leaves_a_future_message_alone(self):
        message = self._schedule(self._later(5))
        connector = self._fake_connector()
        with self._with_connector(connector):
            self.env["omnichannel.message"]._cron_send_scheduled()
        connector.send_message.assert_not_called()
        self.assertEqual(message.state, "scheduled")
