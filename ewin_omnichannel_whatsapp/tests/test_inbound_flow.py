from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInboundFlow(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_whatsapp.channel_whatsapp")
        self.account = self.env["omnichannel.account"].create({
            "name": "WA", "channel_id": self.channel.id,
            "wa_phone_number_id": "PN1", "wa_access_token": "T",
            "wa_app_secret": "S"})

    def _payload(self, msg_id="wamid.1", text="Hello"):
        return {"object": "whatsapp_business_account", "entry": [{"changes": [{
            "field": "messages", "value": {
                "messaging_product": "whatsapp",
                "metadata": {"phone_number_id": "PN1"},
                "contacts": [{"profile": {"name": "Ann"},
                              "wa_id": "15551230000"}],
                "messages": [{"from": "15551230000", "id": msg_id,
                              "timestamp": "1700000000", "type": "text",
                              "text": {"body": text}}]}}]}]}

    def test_inbound_creates_message(self):
        connector = self.env["omnichannel.connector.whatsapp"]
        connector.parse_webhook(self.account, self._payload(), {})
        msg = self.env["omnichannel.message"].search([
            ("account_id", "=", self.account.id), ("direction", "=", "inbound")])
        self.assertEqual(len(msg), 1)
        self.assertIn("Hello", msg.body or "")

    def test_inbound_is_idempotent(self):
        connector = self.env["omnichannel.connector.whatsapp"]
        connector.parse_webhook(self.account, self._payload(), {})
        connector.parse_webhook(self.account, self._payload(), {})
        msg = self.env["omnichannel.message"].search([
            ("account_id", "=", self.account.id), ("direction", "=", "inbound")])
        self.assertEqual(len(msg), 1, "duplicate webhook must not double-create")
