from unittest.mock import patch, MagicMock

from odoo.tests import TransactionCase, tagged
from odoo.addons.ewin_omnichannel_messenger.services.messenger_api_client \
    import MessengerApiClient, MessengerApiError


@tagged("post_install", "-at_install")
class TestApiClient(TransactionCase):
    def _client(self):
        return MessengerApiClient("TOKEN", "PAGE1", "v21.0")

    def _resp(self, status, body):
        r = MagicMock()
        r.status_code = status
        r.content = b"x"
        r.json.return_value = body
        return r

    def test_send_text_returns_message_id(self):
        client = self._client()
        with patch("requests.post", return_value=self._resp(
                200, {"recipient_id": "U1", "message_id": "m_ABC"})) as post:
            res = client.send_text("U1", "hi")
        self.assertEqual(res["message_id"], "m_ABC")
        self.assertIn("/me/messages", post.call_args[0][0])

    def test_window_error_is_non_retriable(self):
        client = self._client()
        body = {"error": {"code": 10, "message": "Outside window",
                          "error_subcode": 2018278}}
        with patch("requests.post", return_value=self._resp(400, body)):
            with self.assertRaises(MessengerApiError) as cm:
                client.send_text("U1", "hi")
        self.assertFalse(cm.exception.retriable)

    def test_rate_limit_is_retriable(self):
        client = self._client()
        body = {"error": {"code": 613, "message": "Rate limited"}}
        with patch("requests.post", return_value=self._resp(429, body)):
            with self.assertRaises(MessengerApiError) as cm:
                client.send_text("U1", "hi")
        self.assertTrue(cm.exception.retriable)

    def test_token_is_redacted_in_network_error(self):
        client = self._client()
        import requests
        with patch("requests.post",
                   side_effect=requests.RequestException("boom TOKEN leak")):
            with self.assertRaises(MessengerApiError) as cm:
                client.send_text("U1", "hi")
        self.assertNotIn("TOKEN", str(cm.exception))

    def test_non_json_error_body_is_classified(self):
        client = self._client()
        r = MagicMock()
        r.status_code = 502
        r.content = b"<html>gateway timeout</html>"
        r.json.side_effect = ValueError("no json")
        with patch("requests.post", return_value=r):
            with self.assertRaises(MessengerApiError) as cm:
                client.send_text("U1", "hi")
        self.assertTrue(cm.exception.retriable)

    def test_download_returns_bytes_and_content_type(self):
        client = self._client()
        r = MagicMock()
        r.content = b"\xff\xd8\xff"
        r.headers = {"Content-Type": "image/jpeg; charset=binary"}
        r.raise_for_status.return_value = None
        with patch("requests.get", return_value=r):
            data, ctype = client.download("https://cdn.example/x.jpg")
        self.assertEqual(data, b"\xff\xd8\xff")
        self.assertEqual(ctype, "image/jpeg")
