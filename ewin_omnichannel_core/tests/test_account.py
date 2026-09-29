from odoo.tests import tagged
from odoo.exceptions import UserError
from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestAccount(OmnichannelCase):
    def test_account_gets_webhook_uuid(self):
        acc = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.assertTrue(acc.webhook_uuid)
        self.assertEqual(len(acc.webhook_uuid), 32)

    def test_account_state_default_draft(self):
        acc = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.assertEqual(acc.state, "draft")

    def test_get_connector_missing_raises(self):
        acc = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        with self.assertRaises(UserError):
            acc._get_connector()

    def test_public_address_is_empty_without_a_connector(self):
        acc = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.assertEqual(acc._get_public_address(), "")

    def test_action_disable(self):
        acc = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        acc.action_disable()
        self.assertEqual(acc.state, "disabled")
        self.assertFalse(acc.active)
