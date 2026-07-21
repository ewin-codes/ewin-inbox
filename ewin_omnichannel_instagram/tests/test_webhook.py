import hashlib
import hmac
import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestInstagramWebhook(HttpCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_instagram.channel_instagram")
        self.account = self.env["omnichannel.account"].create({
            "name": "IG", "channel_id": self.channel.id, "ig_user_id": "IG1",
            "ig_access_token": "T", "ig_app_secret": "S",
            "ig_verify_token": "V", "ig_fetch_profile": False})

    def _url(self):
        return f"/omnichannel/webhook/instagram/{self.account.webhook_uuid}"

    def _sign(self, body):
        return "sha256=" + hmac.new(b"S", body, hashlib.sha256).hexdigest()

    def _payload(self, mid="m_10"):
        return {"object": "instagram", "entry": [{"id": "IG1", "messaging": [{
            "sender": {"id": "USER1"}, "recipient": {"id": "IG1"},
            "timestamp": 1700000000000,
            "message": {"mid": mid, "text": "Hi"}}]}]}

    def test_get_verification_ok(self):
        resp = self.url_open(
            self._url() + "?hub.mode=subscribe&hub.verify_token=V"
            "&hub.challenge=CHAL")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "CHAL")

    def test_get_verification_bad_token(self):
        resp = self.url_open(
            self._url() + "?hub.mode=subscribe&hub.verify_token=WRONG"
            "&hub.challenge=CHAL")
        self.assertEqual(resp.status_code, 403)

    def test_post_good_signature_creates_message(self):
        body = json.dumps(self._payload()).encode()
        resp = self.url_open(self._url(), data=body, headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": self._sign(body)})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(self.env["omnichannel.message"].search([
            ("account_id", "=", self.account.id),
            ("direction", "=", "inbound")]))

    def test_post_bad_signature_rejected(self):
        body = json.dumps(self._payload("m_11")).encode()
        resp = self.url_open(self._url(), data=body, headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=deadbeef"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.env["omnichannel.message"].search([
            ("external_message_id", "=", "m_11")]),
            "bad signature must not be processed")
