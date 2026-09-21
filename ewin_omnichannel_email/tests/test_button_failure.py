from contextlib import ExitStack
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.ewin_omnichannel_email.services.email_client import (
    EmailError)

_CLIENT = "odoo.addons.ewin_omnichannel_email.services.email_client.EmailClient"


@tagged("post_install", "-at_install")
class TestButtonFailure(TransactionCase):
    """A provider failure on an account button reports itself and stays.

    The failure path records what went wrong on the account - the error
    state and ``last_error`` - and Odoo commits a request only when it
    returns successfully. Reporting the failure by raising would roll that
    record back with the rest of the request: the user would read the
    message, and the form behind it would come back looking untouched by
    a failure they had just been told about.
    """

    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_email.channel_email")
        self.account = self.env["omnichannel.account"].create({
            "name": "Mailbox", "channel_id": self.channel.id,
            "email_address": "support@example.com",
            "email_password": "hunter2"})
        self.connector = self.env["omnichannel.connector.email"]

    def _refusing_mailbox(self):
        """Both halves of the check fail: the mailbox refuses the login."""
        stack = ExitStack()
        stack.enter_context(patch(
            _CLIENT + ".connect_imap",
            side_effect=EmailError("IMAP login refused")))
        stack.enter_context(patch(
            _CLIENT + ".check_smtp",
            side_effect=EmailError("SMTP login refused")))
        stack.enter_context(patch(_CLIENT + ".logout"))
        return stack

    def test_a_provider_failure_is_a_sticky_danger_toast(self):
        with self._refusing_mailbox():
            action = self.connector.connect(self.account)
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(action["params"]["type"], "danger")
        self.assertTrue(action["params"]["sticky"])
        self.assertIn("IMAP", action["params"]["message"])
        self.assertIn("SMTP", action["params"]["message"])

    def test_a_provider_failure_survives_the_request(self):
        with self._refusing_mailbox():
            self.connector.connect(self.account)
        self.assertEqual(self.account.state, "error")
        self.assertIn("IMAP login refused", self.account.sudo().last_error)

    def test_fetch_now_reports_a_refused_mailbox(self):
        """Fetch Now has no caller to catch for it.

        poll_account raises on purpose - that is how the poll cron skips
        one account and carries on to the next - so the button is where
        the failure gets caught, recorded and shown.
        """
        self.account.email_imap_host = "imap.example.com"
        with patch(_CLIENT + ".connect_imap",
                   side_effect=EmailError("Connection timed out")):
            action = self.connector.fetch_now(self.account)
        self.assertEqual(action["params"]["type"], "danger")
        self.assertIn("timed out", action["params"]["message"])
        self.assertTrue(self.account.sudo().last_error)
        self.assertTrue(self.env["omnichannel.error.log"].search(
            [("account_id", "=", self.account.id)]))

    def test_a_transient_poll_failure_does_not_park_the_account(self):
        # A timeout is the last thing that went wrong, not a reason to put
        # the account in the error state and stop the poll cron touching it.
        self.account.email_imap_host = "imap.example.com"
        with patch(_CLIENT + ".connect_imap",
                   side_effect=EmailError("Connection timed out")):
            self.connector.fetch_now(self.account)
        self.assertNotEqual(self.account.state, "error")

    def test_a_refused_login_does_park_the_account(self):
        self.account.email_imap_host = "imap.example.com"
        with patch(_CLIENT + ".connect_imap",
                   side_effect=EmailError("Login refused", retriable=False)):
            self.connector.fetch_now(self.account)
        self.assertEqual(self.account.state, "error")

    def _empty_mailbox(self):
        """The mailbox answers and holds nothing new."""
        stack = ExitStack()
        stack.enter_context(patch(_CLIENT + ".connect_imap"))
        stack.enter_context(patch(_CLIENT + ".fetch_unseen", return_value=[]))
        stack.enter_context(patch(_CLIENT + ".logout"))
        return stack

    def test_a_successful_poll_confirms(self):
        self.account.email_imap_host = "imap.example.com"
        with self._empty_mailbox():
            action = self.connector.fetch_now(self.account)
        self.assertEqual(action["params"]["type"], "success")
        self.assertFalse(action["params"]["sticky"])
