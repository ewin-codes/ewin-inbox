from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPublicAddress(TransactionCase):
    """The address a notification names as the one the customer wrote to."""

    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_email.channel_email")

    def test_the_mailbox_is_the_address(self):
        account = self.env["omnichannel.account"].create({
            "name": "Mailbox", "channel_id": self.channel.id,
            "email_address": "support@example.com"})
        self.assertEqual(account._get_public_address(), "support@example.com")

    def test_no_mailbox_gives_an_empty_address(self):
        # A saved email account always has a mailbox — a constraint sees to
        # it — so the empty case is a form that has not been saved yet.
        account = self.env["omnichannel.account"].new({
            "name": "Mailbox", "channel_id": self.channel.id})
        self.assertEqual(account._get_public_address(), "")
