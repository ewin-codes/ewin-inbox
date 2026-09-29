from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPublicAddress(TransactionCase):
    """The address a notification names as the one the customer wrote to."""

    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_instagram.channel_instagram")

    def test_the_username_is_the_address(self):
        account = self.env["omnichannel.account"].create({
            "name": "IG", "channel_id": self.channel.id,
            "ig_username": "shop"})
        self.assertEqual(account._get_public_address(), "@shop")

    def test_no_username_gives_an_empty_address(self):
        account = self.env["omnichannel.account"].create({
            "name": "IG", "channel_id": self.channel.id})
        self.assertEqual(account._get_public_address(), "")
