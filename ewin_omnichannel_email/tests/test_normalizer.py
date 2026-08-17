from email.message import EmailMessage

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEmailNormalizer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_email.channel_email")
        cls.account = cls.env["omnichannel.account"].create(
            {"name": "Mailbox", "channel_id": cls.channel.id,
             "email_address": "box@us.com"})
        cls.norm = cls.env["omnichannel.email.normalizer"]

    def _msg(self, body="Hello", html=None, subject="Hi", frm="Ann <a@x.com>",
             mid="<m1@x.com>", in_reply_to=None, references=None):
        m = EmailMessage()
        m["From"] = frm
        m["To"] = "support@us.com"
        m["Subject"] = subject
        if mid:
            m["Message-ID"] = mid
        if in_reply_to:
            m["In-Reply-To"] = in_reply_to
        if references:
            m["References"] = references
        if html:
            m.set_content(body)
            m.add_alternative(html, subtype="html")
        else:
            m.set_content(body)
        return m

    def test_text_email(self):
        ev = self.norm.normalize_message(self.account, self._msg())
        self.assertEqual(ev["external_message_id"], "<m1@x.com>")
        self.assertEqual(ev["external_user"]["id"], "a@x.com")
        self.assertEqual(ev["external_user"]["name"], "Ann")
        self.assertEqual(ev["message"]["subject"], "Hi")
        self.assertIn("Hello", ev["message"]["text"])

    def test_sender_address_reported_as_the_identity_email(self):
        ev = self.norm.normalize_message(self.account, self._msg())
        self.assertEqual(ev["external_user"]["email"], "a@x.com")

    def test_html_preferred(self):
        ev = self.norm.normalize_message(
            self.account, self._msg(html="<b>Rich</b>"))
        self.assertIn("<b>Rich</b>", ev["message"]["text"])

    def test_thread_reference_extraction(self):
        ev = self.norm.normalize_message(self.account, self._msg(
            in_reply_to="<a@x.com>",
            references="<a@x.com> <b@x.com>"))
        self.assertEqual(ev["thread_reference"], ["<a@x.com>", "<b@x.com>"])
        self.assertEqual(ev["message"]["reply_to_external_message_id"],
                         "<a@x.com>")

    def test_attachment_extracted(self):
        m = self._msg()
        m.add_attachment(b"PDFDATA", maintype="application", subtype="pdf",
                         filename="doc.pdf")
        ev = self.norm.normalize_message(self.account, m)
        att = ev["message"]["attachments"][0]
        self.assertEqual(att["filename"], "doc.pdf")
        self.assertEqual(att["data"], b"PDFDATA")

    def test_missing_message_id_synthesized(self):
        ev = self.norm.normalize_message(self.account, self._msg(mid=None))
        self.assertTrue(ev["external_message_id"])
        self.assertTrue(ev["event_id"].startswith("email:"))

    def test_plaintext_is_escaped_and_newlines_converted(self):
        ev = self.norm.normalize_message(
            self.account, self._msg(body="<script>x</script>\nsecond"))
        text = ev["message"]["text"]
        self.assertIn("&lt;script&gt;", text)      # raw tag escaped
        self.assertNotIn("<script>", text)          # not live markup
        self.assertIn("<br/>", text)                # newline converted

    def test_synthetic_message_id_is_stable(self):
        a = self.norm.normalize_message(self.account, self._msg(mid=None))
        b = self.norm.normalize_message(self.account, self._msg(mid=None))
        self.assertEqual(a["external_message_id"], b["external_message_id"])
        self.assertTrue(a["external_message_id"])
