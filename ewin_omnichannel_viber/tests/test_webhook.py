import hashlib
import hmac
import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestViberWebhook(HttpCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_viber.channel_viber")
        self.account = self.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": self.channel.id,
            "viber_auth_token": "SECRET"})

    def _url(self):
        return f"/omnichannel/viber/webhook/{self.account.webhook_uuid}"

    def _payload(self, token=900):
        return {
            "event": "message", "timestamp": 1457764197627,
            "message_token": token,
            "sender": {"id": "u1", "name": "Ann"},
            "message": {"type": "text", "text": "Hi"},
        }

    def _sign(self, body):
        return hmac.new(b"SECRET", body, hashlib.sha256).hexdigest()

    def test_valid_signature_processes(self):
        body = json.dumps(self._payload()).encode()
        resp = self.url_open(
            self._url(), data=body,
            headers={"Content-Type": "application/json",
                     "X-Viber-Content-Signature": self._sign(body)})
        self.assertEqual(resp.status_code, 200)
        msg = self.env["omnichannel.message"].search(
            [("account_id", "=", self.account.id),
             ("direction", "=", "inbound")], limit=1)
        self.assertTrue(msg, "inbound message must be created synchronously")
        self.assertIn("Hi", msg.body or "")

    def test_bad_signature_rejected(self):
        body = json.dumps(self._payload(token=901)).encode()
        resp = self.url_open(
            self._url(), data=body,
            headers={"Content-Type": "application/json",
                     "X-Viber-Content-Signature": "deadbeef"})
        self.assertEqual(resp.status_code, 200)  # never leak, but not processed
        self.assertFalse(self.env["omnichannel.message"].search(
            [("account_id", "=", self.account.id)]))
