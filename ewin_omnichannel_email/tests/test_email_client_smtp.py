from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.ewin_omnichannel_email.services.email_client import (
    EmailClient, EmailError)

CLIENT = "odoo.addons.ewin_omnichannel_email.services.email_client"


@tagged("post_install", "-at_install")
class TestEmailClientSmtp(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_email.channel_email")
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Support", "channel_id": cls.channel.id,
            "email_address": "support@us.com", "email_password": "secret",
            "email_imap_host": "imap.us.com", "email_smtp_host": "smtp.us.com",
            "email_smtp_port": 587, "email_smtp_security": "starttls"})

    def test_open_smtp_starttls_forces_ipv4_and_keeps_hostname(self):
        """The STARTTLS path must connect to a resolved IPv4 address (so an
        unreachable AAAA record cannot stall the send with [Errno 99]) yet
        restore the real hostname before STARTTLS so TLS/cert validation is
        done against the host, not the IP."""
        server = MagicMock()
        getai = MagicMock(return_value=[
            (2, 1, 6, "", ("172.65.255.143", 587))])  # AF_INET only
        with patch(f"{CLIENT}.smtplib.SMTP", return_value=server) as smtp_cls, \
                patch(f"{CLIENT}.socket.getaddrinfo", getai):
            out = EmailClient(self.account)._open_smtp()
        self.assertIs(out, server)
        # resolution asked for IPv4 explicitly
        self.assertEqual(getai.call_args.args[0], "smtp.us.com")
        self.assertIn(2, getai.call_args.args)  # socket.AF_INET == 2
        # connected to the IP, not the hostname
        server.connect.assert_called_once_with("172.65.255.143", 587)
        # hostname restored before STARTTLS ran (order matters for SNI/cert)
        self.assertEqual(server._host, "smtp.us.com")
        self.assertTrue(server.starttls.called)
        server.login.assert_called_once_with("support@us.com", "secret")

    def test_open_smtp_rejects_plaintext(self):
        """The client refuses to auth over a plaintext connection even if a
        record somehow carries security='none' (defence in depth behind the
        ORM constraint). Set it via raw SQL to bypass that constraint."""
        cr = self.account.env.cr
        cr.execute("UPDATE omnichannel_account SET email_smtp_security='none' "
                   "WHERE id=%s", (self.account.id,))
        self.account.invalidate_recordset(["email_smtp_security"])
        try:
            with self.assertRaises(EmailError):
                EmailClient(self.account)._open_smtp()
        finally:
            cr.execute("UPDATE omnichannel_account "
                       "SET email_smtp_security='starttls' WHERE id=%s",
                       (self.account.id,))
            self.account.invalidate_recordset(["email_smtp_security"])

    def test_first_ipv4_raises_when_no_a_record(self):
        with patch(f"{CLIENT}.socket.getaddrinfo", return_value=[]):
            with self.assertRaises(EmailError):
                EmailClient._first_ipv4("nowhere.invalid", 587)
