import hashlib
import hmac
import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestWhatsAppWebhook(HttpCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_whatsapp.channel_whatsapp")
        self.account = self.env["omnichannel.account"].create({
            "name": "WA", "channel_id": self.channel.id,
            "wa_phone_number_id": "PN1", "wa_access_token": "T",
            "wa_app_secret": "S", "wa_verify_token": "V"})

    def _url(self):
        return f"/omnichannel/webhook/whatsapp/{self.account.webhook_uuid}"

    def _sign(self, body):
        return "sha256=" + hmac.new(b"S", body, hashlib.sha256).hexdigest()

    def _payload(self, msg_id="wamid.10"):
        return {"object": "whatsapp_business_account", "entry": [{"changes": [{
            "field": "messages", "value": {
                "metadata": {"phone_number_id": "PN1"},
                "contacts": [{"profile": {"name": "Ann"},
                              "wa_id": "15551230000"}],
                "messages": [{"from": "15551230000", "id": msg_id,
                              "timestamp": "1700000000", "type": "text",
                              "text": {"body": "Hi"}}]}}]}]}

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
        msg = self.env["omnichannel.message"].search([
            ("account_id", "=", self.account.id), ("direction", "=", "inbound")])
        self.assertTrue(msg)

    def test_post_bad_signature_rejected(self):
        body = json.dumps(self._payload("wamid.11")).encode()
        resp = self.url_open(self._url(), data=body, headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=deadbeef"})
        self.assertEqual(resp.status_code, 200)
        msg = self.env["omnichannel.message"].search([
            ("external_message_id", "=", "wamid.11")])
        self.assertFalse(msg, "bad signature must not be processed")
