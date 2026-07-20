from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

DOWNLOAD_PATH = ("odoo.addons.ewin_omnichannel_viber.services."
                 "viber_api_client.ViberApiClient.download_media")


@tagged("post_install", "-at_install")
class TestViberConnectorInbound(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_viber.channel_viber")
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": cls.channel.id,
            "viber_auth_token": "T"})
        cls.connector = cls.env["omnichannel.connector.viber"]

    def _update(self, message=None, token=5000, uid="abc="):
        return {
            "event": "message", "timestamp": 1457764197627,
            "message_token": token,
            "sender": {"id": uid, "name": "Ivan", "language": "en"},
            "message": message or {"type": "text", "text": "Hello"},
        }

    def test_inbound_text_creates_message(self):
        self.connector.parse_webhook(self.account, self._update(), {})
        conv = self.env["omnichannel.conversation"].search(
            [("account_id", "=", self.account.id)])
        self.assertEqual(len(conv), 1)
        self.assertIn("Hello", conv.omni_message_ids[0].body or "")
        # the receiver id used for replies is the Viber sender id
        self.assertEqual(conv.identity_id.external_id, "abc=")

    def test_inbound_picture_downloads_attachment(self):
        with patch(DOWNLOAD_PATH, return_value=b"imgbytes") as mock_dl:
            self.connector.parse_webhook(self.account, self._update(
                {"type": "picture", "media": "https://ex.com/p.jpg",
                 "text": "hi"}), {})
            self.assertTrue(mock_dl.called)
        msg = self.env["omnichannel.message"].search(
            [("account_id", "=", self.account.id)], limit=1)
        self.assertEqual(msg.message_type, "image")
        self.assertTrue(msg.attachment_ids)

    def test_duplicate_message_token_single_message(self):
        self.connector.parse_webhook(self.account, self._update(token=222), {})
        self.connector.parse_webhook(self.account, self._update(token=222), {})
        msgs = self.env["omnichannel.message"].search(
            [("account_id", "=", self.account.id)])
        self.assertEqual(len(msgs), 1)

    def test_non_message_event_skipped(self):
        res = self.connector.parse_webhook(
            self.account, {"event": "subscribed", "message_token": 1}, {})
        self.assertTrue(res)
        self.assertFalse(self.env["omnichannel.conversation"].search(
            [("account_id", "=", self.account.id)]))
