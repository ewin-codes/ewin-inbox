from odoo.tests import tagged

from .common import NotifyCase


@tagged("post_install", "-at_install")
class TestSchedule(NotifyCase):

    def test_inbound_customer_message_queues_one_job(self):
        message = self._inbound()
        jobs = self._jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs.model, "omnichannel.telegram.notification.service")
        self.assertEqual(jobs.args["message_id"], message.id)
        self.assertEqual(jobs.args["notifier_id"], self.notifier.id)
        self.assertEqual(jobs.company_id, self.company)

    def test_outbound_message_queues_nothing(self):
        self.env["omnichannel.message"].create({
            "conversation_id": self.conversation.id,
            "direction": "outbound", "sender_type": "operator",
            "message_type": "text", "body": "<p>Hi</p>", "state": "sent"})
        self.assertFalse(self._jobs())

    def test_internal_note_queues_nothing(self):
        self.env["omnichannel.message"].create({
            "conversation_id": self.conversation.id,
            "direction": "outbound", "sender_type": "operator",
            "is_internal": True, "message_type": "text",
            "body": "<p>note</p>", "state": "sent"})
        self.assertFalse(self._jobs())

    def test_second_message_inside_the_window_queues_nothing(self):
        self._inbound()
        self._inbound(body="<p>and another</p>")
        self.assertEqual(len(self._jobs()), 1)

    def test_no_notifier_means_no_job(self):
        self.notifier.active = False
        self._inbound()
        self.assertFalse(self._jobs())

    def test_redelivered_update_does_not_notify_twice(self):
        """The provider resends an update it already delivered. The message
        service returns the row it already has; no second row is born, so no
        second notification."""
        event = {
            "event_id": "notifytest:1",
            "external_message_id": "ext-1",
            "external_user": {"id": "4242", "name": "Ann Brown",
                              "username": "ann"},
            "conversation": {"external_id": "4242", "type": "private"},
            "message": {"type": "text", "text": "Hello", "attachments": [],
                        "reply_to_external_message_id": None},
            "raw_payload": {},
        }
        service = self.env["omnichannel.routing.service"]
        first = service.process_event(self.account, event)
        second = service.process_event(self.account, event)
        self.assertEqual(first, second)
        self.assertEqual(len(self._jobs()), 1)

    def test_send_notification_is_the_only_published_job_method(self):
        service = self.env["omnichannel.telegram.notification.service"]
        self.assertEqual(service._job_methods, frozenset({"send_notification"}))

    def test_a_failing_notifier_never_costs_the_customer_their_message(self):
        from unittest.mock import patch
        target = ("odoo.addons.ewin_omnichannel_notify_telegram.services."
                  "notification_service.TelegramNotificationService.schedule")
        with patch(target, side_effect=RuntimeError("boom")):
            message = self._inbound()
        self.assertTrue(message.exists())
        self.assertFalse(self._jobs())

    def test_a_database_error_never_poisons_the_cursor(self):
        """A psycopg2 error, unlike a plain RuntimeError, leaves PostgreSQL's
        session in an aborted-transaction state until something rolls back —
        savepoint or not. Swallowing it bare (no savepoint) would leave the
        channel's own next query on this cursor failing with "current
        transaction is aborted", losing the message the guard exists to
        protect. ``schedule`` is replaced with a callable that issues a real
        broken statement, not a mocked exception object, because only a
        statement PostgreSQL itself rejects actually reproduces that
        server-side abort — raising a bare ``psycopg2.OperationalError``
        instance in Python does not.
        """
        from unittest.mock import patch

        def _break_the_transaction(self, message):
            self.env.cr.execute("SELECT 1/0")  # psycopg2.errors.DivisionByZero

        target = ("odoo.addons.ewin_omnichannel_notify_telegram.services."
                  "notification_service.TelegramNotificationService.schedule")
        with patch(target, _break_the_transaction):
            message = self._inbound()
        self.assertTrue(message.exists())
        self.assertFalse(self._jobs())
        # If the savepoint were missing, this would itself raise "current
        # transaction is aborted, commands ignored until end of transaction
        # block" instead of returning a count.
        self.assertGreaterEqual(
            self.env["omnichannel.message"].search_count([]), 1)
