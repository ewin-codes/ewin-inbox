from datetime import timedelta
from unittest.mock import patch

from email.message import EmailMessage

from odoo import fields
from odoo.tests import TransactionCase, tagged

SEND_PATH = ("odoo.addons.ewin_omnichannel_email.services."
             "email_client.EmailClient.send")


@tagged("post_install", "-at_install")
class TestEmailReply(TransactionCase):
    """What the customer's mail client shows: the reply, the signatures
    under it and the conversation so far — while the thread in Odoo keeps
    each message once, as it was written."""

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
        cls.service = cls.env["omnichannel.message.service"]
        cls.env.user.signature = "<p>--<br/>Mitchell, support lead</p>"

    def _inbound(self, mid, text, reply_to=None):
        m = EmailMessage()
        m["From"] = "Ann <ann@x.com>"
        m["To"] = "support@us.com"
        m["Subject"] = "Order 5"
        m["Message-ID"] = mid
        if reply_to:
            m["In-Reply-To"] = reply_to
        m.set_content(text)
        return self.connector._process_raw(self.account, m.as_bytes())

    def _send(self, conv, body, **kwargs):
        """Reply and return (message, the kwargs EmailClient.send got)."""
        with patch(SEND_PATH, side_effect=lambda **kw: kw["message_id"]) \
                as send:
            message = self.service.create_outbound(conv, body, **kwargs)
        return message, (send.call_args.kwargs if send.called else None)

    # ---- quoting ----

    def test_a_reply_quotes_what_it_answers(self):
        conv = self._inbound("<in1@x.com>", "Where is my order?").conversation_id
        message, sent = self._send(conv, "<p>On its way</p>")
        html = sent["html_body"]
        self.assertLess(html.index("On its way"), html.index("Where is my order?"),
                        "the reply comes first, the quote under it")
        self.assertIn('class="gmail_quote"', html)
        self.assertIn("Ann &lt;ann@x.com&gt; wrote:", html)
        self.assertNotIn("Where is my order?", message.body,
                         "the thread in Odoo keeps the reply as written")

    def test_a_follow_up_quotes_our_own_reply_and_everything_under_it(self):
        conv = self._inbound("<in1@x.com>", "Where is my order?").conversation_id
        self._send(conv, "<p>Checking</p>")
        _message, sent = self._send(conv, "<p>Found it</p>")
        html = sent["html_body"]
        self.assertIn("Support Team &lt;support@us.com&gt; wrote:", html)
        self.assertTrue(
            html.index("Found it") < html.index("Checking")
            < html.index("Where is my order?"),
            "each earlier message nests under the one after it")

    def test_a_customer_answer_is_quoted_as_their_client_sent_it(self):
        """Their email already carries whatever their client quoted, so it is
        not rebuilt — doing so would print the history twice."""
        conv = self._inbound("<in1@x.com>", "Where is my order?").conversation_id
        first, _sent = self._send(conv, "<p>Checking</p>")
        self._inbound("<in2@x.com>", "Thanks", reply_to=first.external_message_id)
        _message, sent = self._send(conv, "<p>Found it</p>")
        html = sent["html_body"]
        self.assertIn("Thanks", html)
        self.assertNotIn("Checking", html)

    def test_notes_and_undelivered_replies_are_not_quoted(self):
        conv = self._inbound("<in1@x.com>", "Where is my order?").conversation_id
        self.service.create_outbound(conv, "<p>Courier is slow</p>",
                                     is_internal=True)
        from odoo.addons.ewin_omnichannel_email.services.email_client \
            import EmailError
        with patch(SEND_PATH, side_effect=EmailError("auth", retriable=False)):
            failed = self.service.create_outbound(conv, "<p>Lost reply</p>")
        self.assertEqual(failed.state, "failed")
        _message, sent = self._send(conv, "<p>On its way</p>")
        html = sent["html_body"]
        self.assertNotIn("Courier is slow", html)
        self.assertNotIn("Lost reply", html)
        self.assertIn("Where is my order?", html)

    def test_a_scheduled_reply_quotes_what_arrived_while_it_waited(self):
        conv = self._inbound("<in1@x.com>", "Where is my order?").conversation_id
        later = fields.Datetime.now() + timedelta(hours=1)
        message = self.service.create_outbound(
            conv, "<p>Good morning</p>", scheduled_at=later)
        self._inbound("<in2@x.com>", "Any news?")
        with patch(SEND_PATH, side_effect=lambda **kw: kw["message_id"]) \
                as send:
            self.service.release_scheduled(message)
        self.assertIn("Any news?", send.call_args.kwargs["html_body"])

    def test_quoting_can_be_switched_off(self):
        self.account.email_quote_history = False
        conv = self._inbound("<in1@x.com>", "Where is my order?").conversation_id
        _message, sent = self._send(conv, "<p>On its way</p>")
        self.assertNotIn("Where is my order?", sent["html_body"])
        self.assertNotIn("gmail_quote", sent["html_body"])

    def test_a_quoted_message_names_its_files(self):
        conv = self._inbound("<in1@x.com>", "Where is my order?").conversation_id
        invoice = self.env["ir.attachment"].create(
            {"name": "invoice.pdf", "raw": b"%PDF"})
        self._send(conv, "<p>Here it is</p>", attachments=invoice)
        _message, sent = self._send(conv, "<p>Did it arrive?</p>")
        self.assertIn("Attachments: invoice.pdf", sent["html_body"])
        self.assertFalse(sent["attachments"],
                         "the file itself travels only with its own email")

    def test_references_carry_the_whole_thread(self):
        conv = self._inbound("<in1@x.com>", "Where is my order?").conversation_id
        first, _sent = self._send(conv, "<p>Checking</p>")
        self._inbound("<in2@x.com>", "Thanks", reply_to=first.external_message_id)
        _message, sent = self._send(conv, "<p>Found it</p>")
        self.assertEqual(
            sent["references"],
            "<in1@x.com> %s <in2@x.com>" % first.external_message_id)
        self.assertEqual(sent["in_reply_to"], "<in2@x.com>")

    # ---- signatures ----

    def test_no_signature_unless_asked_for(self):
        conv = self._inbound("<in1@x.com>", "Hi").conversation_id
        _message, sent = self._send(conv, "<p>Hello</p>")
        self.assertNotIn("o_omni_signature", sent["html_body"])

    def test_operator_signature_then_the_accounts(self):
        self.account.write({
            "email_signature_operator": True,
            "email_signature": "<p>ACME Ltd · acme.example</p>"})
        conv = self._inbound("<in1@x.com>", "Hi").conversation_id
        message, sent = self._send(conv, "<p>Hello</p>")
        html = sent["html_body"]
        self.assertTrue(
            html.index("Hello") < html.index("Mitchell, support lead")
            < html.index("ACME Ltd") < html.index("gmail_quote"),
            "reply, the operator's signature, the account's, then the quote")
        self.assertNotIn("ACME Ltd", message.body)

    def test_the_signature_is_the_replying_operators(self):
        """A scheduled reply goes out from the cron, as the superuser — it is
        still signed by whoever wrote it."""
        self.account.email_signature_operator = True
        colleague = self.env["res.users"].create({
            "name": "Jane", "login": "reply_sig_jane",
            "signature": "<p>Jane, accounts</p>",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        conv = self._inbound("<in1@x.com>", "Hi").conversation_id
        conv.operator_id = colleague
        message = self.env["omnichannel.message"].create({
            "conversation_id": conv.id, "direction": "outbound",
            "sender_type": "operator", "body": "<p>Hello</p>",
            "author_partner_id": colleague.partner_id.id, "state": "queued"})
        html = self.env["omnichannel.email.reply"].html(message)
        self.assertIn("Jane, accounts", html)
        self.assertNotIn("Mitchell", html)
