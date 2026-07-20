from unittest.mock import patch

from email.message import EmailMessage

from odoo.tests import TransactionCase, tagged

SEND_PATH = ("odoo.addons.ewin_omnichannel_email.services."
             "email_client.EmailClient.send")


@tagged("post_install", "-at_install")
class TestEmailOutbound(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_email.channel_email")
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Support", "channel_id": cls.channel.id,
            "email_address": "support@us.com", "email_password": "p",
            "email_from_name": "Support Team",
            "email_imap_host": "imap.us.com", "email_smtp_host": "smtp.us.com"})
        cls.connector = cls.env["omnichannel.connector.email"]

    def _seed_inbound(self, mid="<in1@x.com>"):
        m = EmailMessage()
        m["From"] = "Ann <ann@x.com>"
        m["To"] = "support@us.com"
        m["Subject"] = "Order 5"
        m["Message-ID"] = mid
        m.set_content("hello")
        return self.connector._process_raw(self.account, m.as_bytes())

    def test_outbound_sets_thread_headers_and_marks_sent(self):
        inbound = self._seed_inbound()
        conv = inbound.conversation_id
        with patch(SEND_PATH, return_value="<out1@us.com>") as mock_send:
            msg = self.env["omnichannel.message.service"].create_outbound(
                conv, "<p>On it</p>")
            self.assertTrue(mock_send.called)
            kwargs = mock_send.call_args.kwargs
            self.assertEqual(kwargs["to_addr"], "ann@x.com")
            self.assertTrue(kwargs["subject"].startswith("Re:"))
            self.assertEqual(kwargs["in_reply_to"], "<in1@x.com>")
            self.assertEqual(kwargs["references"], "<in1@x.com>")
            self.assertEqual(kwargs["from_name"], "Support Team")
            self.assertEqual(kwargs["from_addr"], "support@us.com")
        self.assertEqual(msg.state, "sent")
        self.assertEqual(msg.external_message_id, mock_send.call_args.kwargs["message_id"])

    def test_customer_reply_threads_to_outbound(self):
        inbound = self._seed_inbound()
        conv = inbound.conversation_id
        with patch(SEND_PATH, return_value="<ignored@us.com>") as mock_send:
            out = self.env["omnichannel.message.service"].create_outbound(conv, "hi")
        out_mid = out.external_message_id
        # the stored id must be the one actually embedded in the outgoing header
        self.assertEqual(out_mid, mock_send.call_args.kwargs["message_id"])
        # close the conversation and add a decoy closed conversation for the SAME
        # identity with a newer id: the identity-based closed fallback would pick
        # the decoy, so only thread_reference resolution via the stored outbound
        # Message-ID can land the reply in the correct (original) conversation.
        conv.action_close()
        decoy = self.env["omnichannel.conversation"].create({
            "name": "decoy", "account_id": self.account.id,
            "identity_id": conv.identity_id.id, "state": "closed"})
        self.assertGreater(decoy.id, conv.id)
        m = EmailMessage()
        m["From"] = "Ann <ann@x.com>"
        m["To"] = "support@us.com"
        m["Subject"] = "Re: Order 5"
        m["Message-ID"] = "<in2@x.com>"
        m["In-Reply-To"] = out_mid
        m.set_content("thanks")
        reply = self.connector._process_raw(self.account, m.as_bytes())
        self.assertEqual(reply.conversation_id, conv)

    def test_non_retriable_smtp_error_marks_failed(self):
        from odoo.addons.ewin_omnichannel_email.services.email_client \
            import EmailError
        conv = self._seed_inbound().conversation_id
        with patch(SEND_PATH, side_effect=EmailError("auth", retriable=False)):
            msg = self.env["omnichannel.message.service"].create_outbound(
                conv, "boom")
        self.assertEqual(msg.state, "failed")

    def test_retriable_smtp_error_queues(self):
        from odoo.addons.ewin_omnichannel_email.services.email_client \
            import EmailError
        conv = self._seed_inbound().conversation_id
        with patch(SEND_PATH, side_effect=EmailError("net", retriable=True)):
            msg = self.env["omnichannel.message.service"].create_outbound(
                conv, "boom")
        self.assertEqual(msg.state, "queued")
        self.assertTrue(self.env["omnichannel.job"].search(
            [("method", "=", "send_outbound")]))

    def test_smtp_none_security_rejected_on_save(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.env["omnichannel.account"].create({
                "name": "Bad", "channel_id": self.channel.id,
                "email_address": "x@us.com", "email_password": "p",
                "email_imap_host": "imap.us.com", "email_smtp_host": "smtp.us.com",
                "email_smtp_security": "none"})
