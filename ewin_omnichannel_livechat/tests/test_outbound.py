import uuid

from .common import LivechatCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestLivechatOutbound(LivechatCase):
    def _website(self):
        return self.env["website"].search([], limit=1)

    def _open_conversation(self):
        # website.visitor.access_token defaults via a method that requires an
        # HTTP request (raises outside the frontend); set it explicitly, as
        # test_ingestion.py does.
        visitor = self.env["website.visitor"].create({
            "website_id": self._website().id,
            "access_token": uuid.uuid4().hex})
        channel = self._make_session(visitor=visitor)
        self._visitor_post(channel, body="hello")
        conv = self.env["omnichannel.conversation"].search(
            [("account_id", "=", self.account.id)], limit=1)
        conv.operator_id = self.env.user
        return conv, channel

    def test_operator_reply_reaches_the_livechat_channel(self):
        conv, channel = self._open_conversation()
        before = len(channel.message_ids)
        self.env["omnichannel.message.service"].create_outbound(
            conv, "Sure, I can help")
        self.assertTrue(any(
            "Sure, I can help" in (m.body or "")
            for m in channel.message_ids))
        self.assertGreater(len(channel.message_ids), before)
        out = conv.omni_message_ids.filtered(
            lambda m: m.direction == "outbound")
        self.assertEqual(out.state, "sent")

    def test_outbound_is_not_reingested(self):
        conv, channel = self._open_conversation()
        self.env["omnichannel.message.service"].create_outbound(
            conv, "reply body")
        inbound = conv.omni_message_ids.filtered(
            lambda m: m.direction == "inbound")
        self.assertEqual(len(inbound), 1,
                         "our own outbound must not be ingested as inbound")

    def test_download_attachment_returns_independent_copy(self):
        att = self.env["ir.attachment"].create({
            "name": "f.txt", "datas": b"aGVsbG8="})
        result = self.account._get_connector().download_attachment(
            self.account, {"attachment_id": att.id})
        self.assertTrue(result)
        self.assertNotEqual(result.id, att.id)
