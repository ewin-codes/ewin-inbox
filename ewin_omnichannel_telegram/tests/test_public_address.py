from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPublicAddress(TransactionCase):
    """The address a notification names as the one the customer wrote to."""

    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_telegram.channel_telegram")

    def _account(self, **vals):
        return self.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": self.channel.id, **vals})

    def test_the_bot_is_the_address(self):
        account = self._account(tg_bot_username="shop_support_bot")
        self.assertEqual(account._get_public_address(), "@shop_support_bot")

    def test_a_typed_at_sign_is_not_doubled(self):
        account = self._account(tg_bot_username="@shop_support_bot")
        self.assertEqual(account._get_public_address(), "@shop_support_bot")

    def test_no_bot_gives_an_empty_address(self):
        self.assertEqual(self._account()._get_public_address(), "")
