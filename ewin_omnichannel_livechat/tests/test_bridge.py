from .common import LivechatCase
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestLivechatBridge(LivechatCase):
    def test_connect_pins_bridge_presence_online(self):
        self.account._get_connector().connect(self.account)
        presence = self.env["bus.presence"].search(
            [("user_id", "=", self.bridge_user.id)])
        self.assertTrue(presence)
        self.assertEqual(presence.status, "online")
        self.assertEqual(self.account.state, "connected")

    def test_cron_refreshes_presence(self):
        self.env["bus.presence"].search(
            [("user_id", "=", self.bridge_user.id)]).unlink()
        self.env["omnichannel.account"]._cron_livechat_bridge_presence()
        presence = self.env["bus.presence"].search(
            [("user_id", "=", self.bridge_user.id)])
        self.assertEqual(presence.status, "online")

    def test_validate_requires_bridge_in_channel_operators(self):
        stranger = self.env["res.users"].create({
            "name": "Stranger", "login": "lc_stranger"})
        self.account.livechat_bridge_user_id = stranger
        with self.assertRaises(UserError):
            self.account._get_connector().validate_configuration(self.account)

    def test_cron_record_exists(self):
        cron = self.env.ref(
            "ewin_omnichannel_livechat.cron_livechat_bridge_presence")
        self.assertTrue(cron.active)
