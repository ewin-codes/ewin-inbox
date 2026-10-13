import imaplib
from contextlib import ExitStack
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

_CLIENT = "odoo.addons.ewin_omnichannel_email.services.email_client.EmailClient"


@tagged("post_install", "-at_install")
class TestPoll(TransactionCase):
    """poll_account commits each email on its own, then flags it as read.

    The cursor's commit and rollback are patched out: a test transaction
    may not end, and what is under test is which of them the loop reaches
    for, not what Postgres does with it.
    """

    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_email.channel_email")
        self.account = self.env["omnichannel.account"].create({
            "name": "Mailbox", "channel_id": self.channel.id,
            "email_address": "support@example.com",
            "email_password": "hunter2",
            "email_imap_host": "imap.example.com"})
        self.connector = self.env["omnichannel.connector.email"]

    def _mailbox(self, mark_seen_error=None, process_error=None):
        stack = ExitStack()
        stack.enter_context(patch(_CLIENT + ".connect_imap"))
        stack.enter_context(patch(
            _CLIENT + ".fetch_unseen", return_value=[(b"7", b"raw")]))
        stack.enter_context(patch(
            _CLIENT + ".mark_seen", side_effect=mark_seen_error))
        stack.enter_context(patch(_CLIENT + ".logout"))
        stack.enter_context(patch.object(
            type(self.connector), "_process_raw", side_effect=process_error))
        self.commit = stack.enter_context(
            patch.object(self.env.cr, "commit"))
        self.rollback = stack.enter_context(
            patch.object(self.env.cr, "rollback"))
        return stack

    def _logs(self):
        return self.env["omnichannel.error.log"].search(
            [("account_id", "=", self.account.id)])

    def test_a_flag_failure_is_not_reported_as_a_processing_failure(self):
        """The email is already stored when the server refuses the \Seen
        flag. Calling that "Failed to process email" sends whoever reads the
        log looking for a lost message that is sitting in the inbox."""
        with self._mailbox(
                mark_seen_error=imaplib.IMAP4.abort("socket closed")):
            self.connector.poll_account(self.account)
        self.rollback.assert_not_called()
        log = self._logs()
        self.assertEqual(len(log), 1)
        self.assertNotIn("Failed to process", log.summary)
        self.assertIn("read", log.summary)
        self.assertIn("socket closed", log.technical)

    def test_a_processing_failure_is_still_reported_as_one(self):
        with self._mailbox(process_error=ValueError("bad MIME")):
            self.connector.poll_account(self.account)
        self.rollback.assert_called_once()
        self.assertEqual(self._logs().summary, "Failed to process email")
