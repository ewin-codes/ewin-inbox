import uuid

from .common import LivechatCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestLivechatIngestion(LivechatCase):
    def _website(self):
        return self.env["website"].search([], limit=1)

    def _visitor(self):
        # website.visitor.access_token defaults via a method that requires an
        # HTTP request (raises outside the frontend); set it explicitly, as
        # website_visitor._get_access_token itself does for anonymous
        # visitors (see test_identity.py).
        return self.env["website.visitor"].create({
            "website_id": self._website().id,
            "access_token": uuid.uuid4().hex})

    def test_visitor_post_creates_conversation_and_inbound(self):
        visitor = self._visitor()
        channel = self._make_session(visitor=visitor)
        self._visitor_post(channel, body="I need help")
        conv = self.env["omnichannel.conversation"].search(
            [("account_id", "=", self.account.id)])
        self.assertEqual(len(conv), 1)
        self.assertEqual(conv.livechat_channel_id, channel)
        inbound = conv.omni_message_ids.filtered(
            lambda m: m.direction == "inbound")
        self.assertEqual(len(inbound), 1)
        self.assertIn("I need help", inbound.body)

    def test_second_post_reuses_conversation(self):
        visitor = self._visitor()
        channel = self._make_session(visitor=visitor)
        self._visitor_post(channel, body="first")
        self._visitor_post(channel, body="second")
        conv = self.env["omnichannel.conversation"].search(
            [("account_id", "=", self.account.id)])
        self.assertEqual(len(conv), 1)
        inbound = conv.omni_message_ids.filtered(
            lambda m: m.direction == "inbound")
        self.assertEqual(len(inbound), 2)

    def test_operator_post_is_not_ingested(self):
        channel = self._make_session()
        channel.message_post(
            body="operator hi", author_id=self.bridge_user.partner_id.id,
            message_type="comment", subtype_xmlid="mail.mt_comment")
        conv = self.env["omnichannel.conversation"].search(
            [("account_id", "=", self.account.id)])
        self.assertFalse(conv)

    def test_unbridged_channel_is_ignored(self):
        other_lc = self.env["im_livechat.channel"].create({
            "name": "Unbridged", "user_ids": [(6, 0, self.bridge_user.ids)]})
        channel = self.env["discuss.channel"].create({
            "name": "S", "channel_type": "livechat",
            "livechat_channel_id": other_lc.id,
            "livechat_operator_id": self.bridge_user.partner_id.id,
            "livechat_active": True, "anonymous_name": "V",
            "channel_member_ids": [
                (0, 0, {"partner_id": self.bridge_user.partner_id.id})],
        })
        self._visitor_post(channel, body="hi")
        conv = self.env["omnichannel.conversation"].search([])
        self.assertFalse(conv.filtered(
            lambda c: c.livechat_channel_id == channel))
