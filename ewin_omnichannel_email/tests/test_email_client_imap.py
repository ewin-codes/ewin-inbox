import ssl
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.ewin_omnichannel_email.services.email_client import EmailClient

CLIENT = "odoo.addons.ewin_omnichannel_email.services.email_client"


@tagged("post_install", "-at_install")
class TestEmailClientImap(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_email.channel_email")
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Support", "channel_id": cls.channel.id,
            "email_address": "support@us.com", "email_password": "secret",
            "email_imap_host": "imap.us.com", "email_smtp_host": "smtp.us.com",
            "email_smtp_port": 587, "email_smtp_security": "starttls"})

    def _connect(self):
        conn = MagicMock()
        conn.select.return_value = ("OK", [b"1"])
        return conn

    def test_imap_ssl_verifies_the_server_certificate(self):
        """imaplib builds ssl._create_stdlib_context() when handed no context,
        and that one accepts any certificate for any hostname: the session is
        encrypted but the peer is never authenticated, so a MITM collects the
        mailbox password on the very next poll. The client must supply a
        verifying context of its own."""
        conn = self._connect()
        with patch(f"{CLIENT}.imaplib.IMAP4_SSL", return_value=conn) as imap_cls:
            EmailClient(self.account).connect_imap()
        context = imap_cls.call_args.kwargs.get("ssl_context")
        self.assertIsNotNone(
            context, "IMAP4_SSL was built without an explicit ssl_context")
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_imap_starttls_verifies_the_server_certificate(self):
        self.account.email_imap_ssl = False
        conn = self._connect()
        with patch(f"{CLIENT}.imaplib.IMAP4", return_value=conn):
            EmailClient(self.account).connect_imap()
        context = conn.starttls.call_args.args[0]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
