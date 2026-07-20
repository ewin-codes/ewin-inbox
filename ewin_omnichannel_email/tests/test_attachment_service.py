from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEmailAttachmentService(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_email.channel_email")
        cls.account = cls.env["omnichannel.account"].create(
            {"name": "Mailbox", "channel_id": cls.channel.id,
             "email_address": "box@us.com", "email_max_file_size": 1})
        cls.svc = cls.env["omnichannel.email.attachment.service"]

    def test_stores_and_sanitizes(self):
        att = self.svc.store(self.account, b"hi", "../evil name.pdf",
                             "application/pdf")
        self.assertEqual(att.name, "evil name.pdf")
        self.assertEqual(att.mimetype, "application/pdf")

    def test_blocks_dangerous_mimetype(self):
        att = self.svc.store(self.account, b"<svg/>", "x.svg", "image/svg+xml")
        # Service neutralizes the passed-in mimetype to
        # "application/octet-stream", but ir.attachment.create() re-sniffs
        # content ("application/octet-stream" always triggers a re-guess in
        # _compute_mimetype). guess_mimetype() correctly re-detects the raw
        # bytes as image/svg+xml; with attachments_mime_plainxml=True in
        # context, _check_contents then force-downgrades that xml-like
        # result to text/plain (mirrors core's own neuter_mimetype
        # defense-in-depth). Either way the dangerous image/svg+xml value
        # never survives.
        self.assertEqual(att.mimetype, "text/plain")

    def test_oversize_raises(self):
        with self.assertRaises(ValueError):
            self.svc.store(self.account, b"x" * (2 * 1024 * 1024), "big.bin",
                           "application/octet-stream")
