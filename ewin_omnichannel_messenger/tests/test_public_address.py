from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPublicAddress(TransactionCase):
    """The address a notification names as the one the customer wrote to."""

    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_messenger.channel_messenger")

    def test_the_page_is_the_address(self):
        account = self.env["omnichannel.account"].create({
            "name": "MG", "channel_id": self.channel.id,
            "mg_page_name": "Shop Page"})
        self.assertEqual(account._get_public_address(), "Shop Page")

    def test_no_page_gives_an_empty_address(self):
        account = self.env["omnichannel.account"].create({
            "name": "MG", "channel_id": self.channel.id})
        self.assertEqual(account._get_public_address(), "")
