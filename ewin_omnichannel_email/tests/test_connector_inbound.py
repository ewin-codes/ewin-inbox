from email.message import EmailMessage

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEmailInbound(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_email.channel_email")
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Support", "channel_id": cls.channel.id,
            "email_address": "support@us.com", "email_password": "p",
            "email_imap_host": "imap.us.com", "email_smtp_host": "smtp.us.com"})
        cls.connector = cls.env["omnichannel.connector.email"]

    def _raw(self, subject="Hi", body="Hello", frm="Ann <ann@x.com>",
             mid="<m1@x.com>", in_reply_to=None, references=None):
        m = EmailMessage()
        m["From"] = frm
        m["To"] = "support@us.com"
        m["Subject"] = subject
        m["Message-ID"] = mid
        if in_reply_to:
            m["In-Reply-To"] = in_reply_to
        if references:
            m["References"] = references
        m.set_content(body)
        return m.as_bytes()

    def test_inbound_creates_conversation_and_sets_partner_email(self):
        msg = self.connector._process_raw(self.account, self._raw())
        conv = msg.conversation_id
        self.assertEqual(conv.identity_id.external_id, "ann@x.com")
        self.assertIn("Hello", msg.body or "")
        self.assertEqual(conv.subject, "Hi")  # subject stored in its own field
        self.assertNotEqual(conv.name, "Hi")  # name is the customer, not subject
        self.assertEqual(conv.partner_id.email, "ann@x.com")

    def test_reply_threads_into_same_conversation(self):
        first = self.connector._process_raw(self.account, self._raw(mid="<a@x.com>"))
        reply = self.connector._process_raw(
            self.account,
            self._raw(mid="<b@x.com>", subject="Re: Hi",
                      in_reply_to="<a@x.com>", references="<a@x.com>"))
        self.assertEqual(reply.conversation_id, first.conversation_id)

    def test_reply_reopens_closed_conversation(self):
        first = self.connector._process_raw(self.account, self._raw(mid="<a@x.com>"))
        first.conversation_id.action_close()
        reply = self.connector._process_raw(
            self.account,
            self._raw(mid="<b@x.com>", in_reply_to="<a@x.com>"))
        self.assertEqual(reply.conversation_id, first.conversation_id)
        self.assertNotEqual(reply.conversation_id.state, "closed")

    def test_duplicate_message_id_single_message(self):
        self.connector._process_raw(self.account, self._raw(mid="<dup@x.com>"))
        self.connector._process_raw(self.account, self._raw(mid="<dup@x.com>"))
        msgs = self.env["omnichannel.message"].search(
            [("account_id", "=", self.account.id)])
        self.assertEqual(len(msgs), 1)

    def test_inbound_attachment_stored(self):
        m = EmailMessage()
        m["From"] = "Ann <ann@x.com>"
        m["To"] = "support@us.com"
        m["Subject"] = "Doc"
        m["Message-ID"] = "<att@x.com>"
        m.set_content("see attached")
        m.add_attachment(b"PDF", maintype="application", subtype="pdf",
                         filename="doc.pdf")
        msg = self.connector._process_raw(self.account, m.as_bytes())
        self.assertTrue(msg.attachment_ids)
        self.assertEqual(msg.attachment_ids[0].name, "doc.pdf")
