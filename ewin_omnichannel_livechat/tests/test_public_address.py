from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPublicAddress(TransactionCase):
    """The address a notification names as the one the customer wrote to."""

    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_livechat.channel_livechat")

    def test_the_livechat_channel_is_the_address(self):
        lc_channel = self.env["im_livechat.channel"].create(
            {"name": "Site Chat"})
        account = self.env["omnichannel.account"].create({
            "name": "Chat", "channel_id": self.channel.id,
            "livechat_channel_id": lc_channel.id})
        self.assertEqual(account._get_public_address(), "Site Chat")

    def test_no_livechat_channel_gives_an_empty_address(self):
        account = self.env["omnichannel.account"].create({
            "name": "Chat", "channel_id": self.channel.id})
        self.assertEqual(account._get_public_address(), "")
