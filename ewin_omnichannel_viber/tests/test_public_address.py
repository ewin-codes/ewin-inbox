from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPublicAddress(TransactionCase):
    """The address a notification names as the one the customer wrote to."""

    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_viber.channel_viber")

    def test_the_bot_name_is_the_address(self):
        account = self.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": self.channel.id,
            "viber_bot_name": "Shop Support"})
        self.assertEqual(account._get_public_address(), "Shop Support")

    def test_no_bot_name_gives_an_empty_address(self):
        account = self.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": self.channel.id})
        self.assertEqual(account._get_public_address(), "")
