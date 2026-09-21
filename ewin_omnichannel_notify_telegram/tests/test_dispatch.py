from odoo.exceptions import AccessError
from odoo.service.model import get_public_method
from odoo.tests import tagged

from odoo.addons.ewin_omnichannel_core.models.omnichannel_job import (
    NonRetriableError)

from ..services.notify_api_client import TelegramNotifyError
from .common import NotifyCase


@tagged("post_install", "-at_install")
class TestDispatch(NotifyCase):

    def setUp(self):
        super().setUp()
        self.service = self.env["omnichannel.telegram.notification.service"]
        self.operator = self.env["res.users"].create({
            "name": "Olga Operator", "login": "olga_notify_test"})

    def test_send_notification_and_schedule_are_not_callable_over_rpc(self):
        # get_public_method is what odoo/service/model.py's call_kw consults
        # before letting an authenticated RPC caller invoke a method. Both
        # sudo() their arguments, so without @api.private any operator could
        # call them directly with a notifier/message id pair of their own
        # choosing, sidestepping every record rule that normally hides a
        # conversation from them.
        with self.assertRaises(AccessError):
            get_public_method(self.service, "send_notification")
        with self.assertRaises(AccessError):
            get_public_method(self.service, "schedule")

    def _send(self, client):
        message = self._inbound()
        with self._with_client(client):
            self.service.send_notification(self.notifier.id, message.id)
        return message

    def test_unassigned_conversation_notifies_the_group(self):
        client = self._fake_client()
        self._send(client)
        chat_id = client.send_message.call_args[0][0]
        self.assertEqual(chat_id, "-100777")

    def test_assigned_operator_with_telegram_is_notified_personally(self):
        self.operator.sudo().omni_tg_chat_id = "555"
        self.conversation.operator_id = self.operator
        client = self._fake_client()
        self._send(client)
        self.assertEqual(client.send_message.call_args[0][0], "555")

    def test_assigned_operator_without_telegram_falls_back_to_the_group(self):
        self.conversation.operator_id = self.operator
        client = self._fake_client()
        self._send(client)
        self.assertEqual(client.send_message.call_args[0][0], "-100777")

    def test_no_recipient_at_all_is_a_configuration_entry_in_the_log(self):
        self.notifier.group_chat_id = False
        client = self._fake_client()
        self._send(client)
        client.send_message.assert_not_called()
        log = self.env["omnichannel.error.log"].search(
            [("category", "=", "configuration")], limit=1, order="id desc")
        self.assertTrue(log)

    def test_a_revoked_token_is_terminal_and_logged(self):
        # TransactionCase.assertRaises wraps its block in a cr.savepoint()
        # that gets rolled back once the expected exception is caught, which
        # would silently undo the notifier and error-log writes made just
        # before the raise. A plain try/except keeps them visible for the
        # assertions below, matching what really happens in production (the
        # job queue catches NonRetriableError without rolling back the
        # transaction). See ewin_omnichannel_telegram/tests/
        # test_connector_outbound.py for the same pattern.
        client = self._fake_client()
        client.send_message.side_effect = TelegramNotifyError(
            401, "Unauthorized", retriable=False)
        message = self._inbound()
        raised = False
        with self._with_client(client):
            try:
                self.service.send_notification(self.notifier.id, message.id)
            except NonRetriableError:
                raised = True
        self.assertTrue(raised, "NonRetriableError was not raised")
        self.assertEqual(self.notifier.state, "error")
        self.assertIn("Unauthorized", self.notifier.last_error)
        self.assertTrue(self.env["omnichannel.error.log"].search(
            [("category", "=", "provider")], limit=1))

    def test_a_transient_failure_is_raised_for_the_queue_to_retry(self):
        client = self._fake_client()
        client.send_message.side_effect = TelegramNotifyError(
            500, "Internal Server Error", retriable=True)
        message = self._inbound()
        with self._with_client(client), self.assertRaises(TelegramNotifyError):
            self.service.send_notification(self.notifier.id, message.id)

    def test_a_successful_send_clears_a_previous_error(self):
        self.notifier.write({"state": "error", "last_error": "old"})
        self._send(self._fake_client())
        self.assertEqual(self.notifier.state, "connected")
        self.assertFalse(self.notifier.last_error)

    def test_a_deleted_message_is_a_quiet_no_op(self):
        message = self._inbound()
        message_id = message.id
        message.unlink()
        client = self._fake_client()
        with self._with_client(client):
            self.assertFalse(
                self.service.send_notification(self.notifier.id, message_id))
        client.send_message.assert_not_called()

    def test_a_deleted_notifier_is_a_quiet_no_op(self):
        message = self._inbound()
        notifier_id = self.notifier.id
        self.notifier.unlink()
        client = self._fake_client()
        with self._with_client(client):
            self.assertFalse(
                self.service.send_notification(notifier_id, message.id))
        client.send_message.assert_not_called()

    def test_an_archived_notifier_is_a_quiet_no_op(self):
        message = self._inbound()
        self.notifier.active = False
        client = self._fake_client()
        with self._with_client(client):
            self.assertFalse(
                self.service.send_notification(self.notifier.id, message.id))
        client.send_message.assert_not_called()

    def test_a_notifier_without_a_token_does_not_reach_the_network(self):
        self.notifier.sudo().bot_token = False
        message = self._inbound()
        client = self._fake_client()
        with self._with_client(client):
            self.service.send_notification(self.notifier.id, message.id)
        client.send_message.assert_not_called()
        log = self.env["omnichannel.error.log"].search(
            [("category", "=", "configuration")], limit=1, order="id desc")
        self.assertTrue(log)
        self.assertIn("bot token", log.summary)

    def test_the_queue_runs_the_job_end_to_end(self):
        client = self._fake_client()
        self._inbound()
        job = self._jobs()
        with self._with_client(client):
            job.run()
        self.assertEqual(job.state, "done")
        client.send_message.assert_called_once()
