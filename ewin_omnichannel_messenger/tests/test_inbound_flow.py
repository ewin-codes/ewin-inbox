from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInboundFlow(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_messenger.channel_messenger")
        self.account = self.env["omnichannel.account"].create({
            "name": "MG", "channel_id": self.channel.id, "mg_page_id": "PAGE1",
            "mg_page_access_token": "T", "mg_app_secret": "S",
            "mg_fetch_profile": False})

    def _payload(self, mid="m_1", text="Hello"):
        return {"object": "page", "entry": [{"id": "PAGE1", "messaging": [{
            "sender": {"id": "USER1"}, "recipient": {"id": "PAGE1"},
            "timestamp": 1700000000000,
            "message": {"mid": mid, "text": text}}]}]}

    def test_inbound_creates_message(self):
        connector = self.env["omnichannel.connector.messenger"]
        connector.parse_webhook(self.account, self._payload(), {})
        msg = self.env["omnichannel.message"].search([
            ("account_id", "=", self.account.id), ("direction", "=", "inbound")])
        self.assertEqual(len(msg), 1)
        self.assertIn("Hello", msg.body or "")

    def test_inbound_is_idempotent(self):
        connector = self.env["omnichannel.connector.messenger"]
        connector.parse_webhook(self.account, self._payload(), {})
        connector.parse_webhook(self.account, self._payload(), {})
        msg = self.env["omnichannel.message"].search([
            ("account_id", "=", self.account.id), ("direction", "=", "inbound")])
        self.assertEqual(len(msg), 1, "duplicate webhook must not double-create")

    def test_echo_is_ignored(self):
        connector = self.env["omnichannel.connector.messenger"]
        payload = {"object": "page", "entry": [{"messaging": [{
            "sender": {"id": "PAGE1"}, "recipient": {"id": "USER1"},
            "message": {"mid": "m_echo", "text": "hi", "is_echo": True}}]}]}
        connector.parse_webhook(self.account, payload, {})
        self.assertFalse(self.env["omnichannel.message"].search([
            ("external_message_id", "=", "m_echo")]))

    def test_page_id_learned_from_first_event(self):
        account = self.env["omnichannel.account"].create({
            "name": "MG2", "channel_id": self.channel.id,
            "mg_page_access_token": "T", "mg_fetch_profile": False})
        self.assertFalse(account.mg_page_id)
        self.env["omnichannel.connector.messenger"].parse_webhook(
            account, self._payload(mid="m_learn"), {})
        self.assertEqual(account.mg_page_id, "PAGE1")
        self.assertTrue(self.env["omnichannel.message"].search([
            ("account_id", "=", account.id), ("direction", "=", "inbound")]))

    def test_mismatched_page_entry_is_skipped(self):
        # account bound to a different Page id: the entry must be ignored.
        self.account.mg_page_id = "OTHER_PAGE"
        self.env["omnichannel.connector.messenger"].parse_webhook(
            self.account, self._payload(mid="m_x"), {})
        self.assertFalse(self.env["omnichannel.message"].search([
            ("external_message_id", "=", "m_x")]))

    def test_profile_enrichment_names_the_contact(self):
        self.account.mg_fetch_profile = True
        connector = self.env["omnichannel.connector.messenger"]
        profile = {"first_name": "Ann", "last_name": "Lee",
                   "profile_pic": "https://cdn.example/p.jpg"}
        with patch("odoo.addons.ewin_omnichannel_messenger.models."
                   "messenger_connector.MessengerConnector."
                   "get_external_profile", return_value=profile):
            connector.parse_webhook(self.account, self._payload(), {})
        identity = self.env["omnichannel.identity"].search([
            ("account_id", "=", self.account.id), ("external_id", "=", "USER1")])
        self.assertEqual(identity.display_name, "Ann Lee")
        self.assertEqual(identity.partner_id.name, "Ann Lee")
