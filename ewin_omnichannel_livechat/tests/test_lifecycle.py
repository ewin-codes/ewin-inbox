import uuid

from .common import LivechatCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestLivechatLifecycle(LivechatCase):
    def _website(self):
        return self.env["website"].search([], limit=1)

    def _conversation(self):
        # website.visitor.access_token defaults via a method that requires an
        # HTTP request (raises outside the frontend); set it explicitly, as
        # test_ingestion.py does.
        visitor = self.env["website.visitor"].create({
            "website_id": self._website().id,
            "access_token": uuid.uuid4().hex})
        channel = self._make_session(visitor=visitor)
        self._visitor_post(channel, body="hi")
        conv = self.env["omnichannel.conversation"].search(
            [("account_id", "=", self.account.id)], limit=1)
        return conv, channel

    def test_visitor_leave_sets_conversation_pending(self):
        conv, channel = self._conversation()
        channel._close_livechat_session()
        self.assertEqual(conv.state, "pending")

    def test_ewin_close_posts_notice_and_ends_session(self):
        conv, channel = self._conversation()
        conv.operator_id = self.env.user
        conv.action_close()
        self.assertEqual(conv.state, "closed")
        self.assertFalse(channel.livechat_active)
        self.assertTrue(any(
            "closed" in (m.body or "").lower() for m in channel.message_ids))
        # closing notice must not create a new inbound omni message
        inbound = conv.omni_message_ids.filtered(
            lambda m: m.direction == "inbound")
        self.assertEqual(len(inbound), 1)
