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

    def test_close_button_leaves_the_session_alone_when_a_reason_is_wanted(
            self):
        """action_close() opens the close-reason wizard instead of closing
        when the policy asks why (Finding 1 regression). The visitor-facing
        side effects belong to the actual state transition, ``_close``: if
        action_close ended the session and posted the notice regardless, an
        operator who then hits Discard (or a 'required' validation error)
        would leave the visitor told the chat is over and the session dead,
        with the conversation itself stuck in pending."""
        conv, channel = self._conversation()
        conv.operator_id = self.env.user
        self.env["ir.config_parameter"].sudo().set_param(
            "ewin_omnichannel.close_reason_policy", "required")
        action = conv.action_close()
        self.assertEqual(action["res_model"], "omnichannel.close.wizard")
        self.assertNotEqual(conv.state, "closed")
        self.assertTrue(channel.livechat_active)
        self.assertFalse(any(
            "closed" in (m.body or "").lower() for m in channel.message_ids))
