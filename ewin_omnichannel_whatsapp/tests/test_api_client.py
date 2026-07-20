from unittest.mock import patch, MagicMock

from odoo.tests import TransactionCase, tagged
from odoo.addons.ewin_omnichannel_whatsapp.services.whatsapp_api_client import (
    WhatsAppApiClient, WhatsAppApiError)


@tagged("post_install", "-at_install")
class TestApiClient(TransactionCase):
    def _client(self):
        return WhatsAppApiClient("TOKEN", "PN1", "WABA1", "v21.0")

    def _resp(self, status, body):
        r = MagicMock()
        r.status_code = status
        r.content = b"x"
        r.json.return_value = body
        return r

    def test_send_text_returns_message_id(self):
        client = self._client()
        with patch("requests.post", return_value=self._resp(
                200, {"messages": [{"id": "wamid.ABC"}]})) as post:
            res = client.send_text("15551234567", "hi")
        self.assertEqual(res["messages"][0]["id"], "wamid.ABC")
        url = post.call_args[0][0]
        self.assertIn("/PN1/messages", url)

    def test_window_error_is_non_retriable(self):
        client = self._client()
        body = {"error": {"code": 131047, "message": "Re-engagement",
                          "error_subcode": 0}}
        with patch("requests.post", return_value=self._resp(400, body)):
            with self.assertRaises(WhatsAppApiError) as cm:
                client.send_text("15551234567", "hi")
        self.assertFalse(cm.exception.retriable)

    def test_rate_limit_is_retriable(self):
        client = self._client()
        body = {"error": {"code": 130429, "message": "Rate limit"}}
        with patch("requests.post", return_value=self._resp(429, body)):
            with self.assertRaises(WhatsAppApiError) as cm:
                client.send_text("15551234567", "hi")
        self.assertTrue(cm.exception.retriable)

    def test_token_is_redacted_in_network_error(self):
        client = self._client()
        import requests
        with patch("requests.post",
                   side_effect=requests.RequestException("boom TOKEN leak")):
            with self.assertRaises(WhatsAppApiError) as cm:
                client.send_text("15551234567", "hi")
        self.assertNotIn("TOKEN", str(cm.exception))

    def test_non_json_error_body_is_classified(self):
        client = self._client()
        r = MagicMock()
        r.status_code = 502
        r.content = b"<html>gateway timeout</html>"
        r.json.side_effect = ValueError("no json")
        with patch("requests.post", return_value=r):
            with self.assertRaises(WhatsAppApiError) as cm:
                client.send_text("15551234567", "hi")
        self.assertTrue(cm.exception.retriable)
