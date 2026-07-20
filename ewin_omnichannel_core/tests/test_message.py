from odoo.tests import tagged
from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestMessage(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "123"})
        self.conv = self.env["omnichannel.conversation"].create({
            "name": "Conv", "account_id": self.account.id,
            "identity_id": self.identity.id})

    def test_inbound_message_defaults(self):
        msg = self.env["omnichannel.message"].create({
            "conversation_id": self.conv.id, "direction": "inbound",
            "sender_type": "customer", "body": "Hello"})
        self.assertEqual(msg.state, "received")
        self.assertEqual(msg.account_id, self.account)
        self.assertEqual(msg.company_id, self.conv.company_id)

    def test_body_html_sanitized(self):
        msg = self.env["omnichannel.message"].create({
            "conversation_id": self.conv.id, "direction": "inbound",
            "sender_type": "customer",
            "body": "<script>alert(1)</script><b>hi</b>"})
        self.assertNotIn("<script>", msg.body or "")
