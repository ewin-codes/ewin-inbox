import hashlib
import hmac
import json

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestMessengerWebhook(HttpCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_messenger.channel_messenger")
        self.account = self.env["omnichannel.account"].create({
            "name": "MG", "channel_id": self.channel.id, "mg_page_id": "PAGE1",
            "mg_page_access_token": "T", "mg_app_secret": "S",
            "mg_verify_token": "V", "mg_fetch_profile": False})

    def _url(self):
        return f"/omnichannel/webhook/messenger/{self.account.webhook_uuid}"

    def _sign(self, body):
        return "sha256=" + hmac.new(b"S", body, hashlib.sha256).hexdigest()

    def _payload(self, mid="m_10"):
        return {"object": "page", "entry": [{"id": "PAGE1", "messaging": [{
            "sender": {"id": "USER1"}, "recipient": {"id": "PAGE1"},
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

    # The header and the query string both reach Python as text a caller
    # controls: WSGI decodes a header value as Latin-1, a query string as
    # UTF-8. hmac.compare_digest raises TypeError when a str argument holds
    # a character outside ASCII, so comparing them as str turned one crafted
    # byte into an error page — an answer that differs from an ordinary
    # rejection and so tells an unauthenticated caller that this account
    # exists and has a secret set. Every rejection has to look the same.
    def test_non_ascii_verify_token_is_an_ordinary_403(self):
        resp = self.url_open(
            self._url() + "?hub.mode=subscribe&hub.verify_token=%C3%A9"
            "&hub.challenge=CHAL")
        self.assertEqual(resp.status_code, 403)

    def test_non_ascii_signature_header_is_an_ordinary_rejection(self):
        body = json.dumps(self._payload("m_90")).encode()
        resp = self.url_open(self._url(), data=body, headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "é"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.env["omnichannel.message"].search(
            [("account_id", "=", self.account.id),
             ("direction", "=", "inbound")]))
