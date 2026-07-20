from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStatus(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_whatsapp.channel_whatsapp")
        self.account = self.env["omnichannel.account"].create({
            "name": "WA", "channel_id": self.channel.id,
            "wa_phone_number_id": "PN1", "wa_access_token": "T"})
        self.identity = self.env["omnichannel.identity"].create({
            "account_id": self.account.id, "external_id": "15551230000"})
        self.conversation = self.env["omnichannel.conversation"].create({
            "account_id": self.account.id, "identity_id": self.identity.id})
        self.msg = self.env["omnichannel.message"].create({
            "conversation_id": self.conversation.id, "direction": "outbound",
            "sender_type": "operator", "message_type": "text", "body": "hi",
            "state": "sent", "external_message_id": "wamid.OUT"})

    def _status(self, status, errors=None):
        return {"id": "wamid.OUT", "status": status, "timestamp": "1700000000",
                "recipient_id": "15551230000", "errors": errors or []}

    def test_delivered_then_read_advances(self):
        connector = self.env["omnichannel.connector.whatsapp"]
        connector.apply_status(self.account, self._status("delivered"))
        self.assertEqual(self.msg.state, "delivered")
        self.assertTrue(self.msg.delivered_at)
        connector.apply_status(self.account, self._status("read"))
        self.assertEqual(self.msg.state, "read")
        self.assertTrue(self.msg.read_at)

    def test_out_of_order_does_not_regress(self):
        connector = self.env["omnichannel.connector.whatsapp"]
        connector.apply_status(self.account, self._status("read"))
        self.assertEqual(self.msg.state, "read")
        connector.apply_status(self.account, self._status("delivered"))
        self.assertEqual(self.msg.state, "read", "must not regress read->delivered")

    def test_failed_records_error(self):
        connector = self.env["omnichannel.connector.whatsapp"]
        connector.apply_status(self.account, self._status(
            "failed", errors=[{"code": 131026, "title": "Undeliverable"}]))
        self.assertEqual(self.msg.state, "failed")
        self.assertEqual(self.msg.error_code, "131026")
