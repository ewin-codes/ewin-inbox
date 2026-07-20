from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLivechatInstall(TransactionCase):
    def test_channel_and_connector_registered(self):
        channel = self.env["omnichannel.channel"].search(
            [("code", "=", "livechat")])
        self.assertTrue(channel, "livechat omnichannel.channel must exist")
        account = self.env["omnichannel.account"].create({
            "name": "LC", "channel_id": channel.id})
        connector = account._get_connector()
        self.assertEqual(connector._name, "omnichannel.connector.livechat")
        self.assertTrue(
            hasattr(account, "livechat_channel_id"),
            "account must expose livechat_channel_id")
