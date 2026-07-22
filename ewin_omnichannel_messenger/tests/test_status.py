from odoo import fields
from odoo.tests import TransactionCase, tagged

# A watermark far in the future, so it covers any message sent "now".
FUTURE_WATERMARK = 32503680000000  # ~ year 3000, in ms


@tagged("post_install", "-at_install")
class TestStatus(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_messenger.channel_messenger")
        self.account = self.env["omnichannel.account"].create({
            "name": "MG", "channel_id": self.channel.id, "mg_page_id": "PAGE1",
            "mg_page_access_token": "T"})
        self.identity = self.env["omnichannel.identity"].create({
            "account_id": self.account.id, "external_id": "USER1"})
        self.conversation = self.env["omnichannel.conversation"].create({
            "account_id": self.account.id, "identity_id": self.identity.id})
        self.msg = self.env["omnichannel.message"].create({
            "conversation_id": self.conversation.id, "direction": "outbound",
            "sender_type": "operator", "message_type": "text", "body": "hi",
            "state": "sent", "external_message_id": "m_OUT",
            "sent_at": fields.Datetime.now()})

    def _delivery_mids(self, mids):
        return {"delivery": {"mids": mids, "watermark": FUTURE_WATERMARK}}

    def _read(self):
        return {"read": {"watermark": FUTURE_WATERMARK}}

    def test_delivery_by_mid_then_read_by_watermark(self):
        connector = self.env["omnichannel.connector.messenger"]
        connector.apply_delivery(self.account, self._delivery_mids(["m_OUT"]))
        self.assertEqual(self.msg.state, "delivered")
        self.assertTrue(self.msg.delivered_at)
        connector.apply_read(self.account, self._read())
        self.assertEqual(self.msg.state, "read")
        self.assertTrue(self.msg.read_at)

    def test_delivery_by_watermark(self):
        connector = self.env["omnichannel.connector.messenger"]
        connector.apply_delivery(
            self.account, {"delivery": {"watermark": FUTURE_WATERMARK}})
        self.assertEqual(self.msg.state, "delivered")

    def test_read_does_not_regress_to_delivered(self):
        connector = self.env["omnichannel.connector.messenger"]
        connector.apply_read(self.account, self._read())
        self.assertEqual(self.msg.state, "read")
        connector.apply_delivery(self.account, self._delivery_mids(["m_OUT"]))
        self.assertEqual(self.msg.state, "read",
                         "must not regress read->delivered")

    def test_old_watermark_does_not_touch_newer_message(self):
        connector = self.env["omnichannel.connector.messenger"]
        connector.apply_delivery(
            self.account, {"delivery": {"watermark": 1}})  # 1970
        self.assertEqual(self.msg.state, "sent")
