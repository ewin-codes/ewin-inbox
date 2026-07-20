import json
import uuid

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestWebhook(HttpCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_telegram.channel_telegram")
        self.account = self.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": self.channel.id,
            "tg_bot_token": "T", "tg_webhook_secret": "S"})

    def _url(self):
        return f"/omnichannel/webhook/telegram/{self.account.webhook_uuid}"

    def test_webhook_processes_synchronously(self):
        # inbound is processed inline (no cron wait) so the message reaches the
        # operator instantly; a successful path enqueues no job.
        payload = {"update_id": 900, "message": {
            "message_id": 1, "date": 1700000000,
            "from": {"id": 77, "first_name": "Ann", "username": "ann"},
            "chat": {"id": 77, "type": "private"}, "text": "Hi"}}
        resp = self.url_open(
            self._url(),
            data=json.dumps(payload),
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": "S"})
        self.assertEqual(resp.status_code, 200)
        msg = self.env["omnichannel.message"].search(
            [("account_id", "=", self.account.id),
             ("direction", "=", "inbound")], limit=1)
        self.assertTrue(msg, "inbound message must be created synchronously")
        self.assertIn("Hi", msg.body or "")
        # no fallback job on the happy path
        self.assertFalse(self.env["omnichannel.job"].search(
            [("method", "=", "parse_webhook_job")]))

    def _job_count(self):
        return self.env["omnichannel.job"].search_count(
            [("method", "=", "parse_webhook_job")])

    def test_bad_secret_returns_200_no_job(self):
        payload = {"update_id": 901, "message": {
            "message_id": 2, "date": 1700000001,
            "from": {"id": 78, "first_name": "Bob", "username": "bob"},
            "chat": {"id": 78, "type": "private"}, "text": "Hi"}}
        before = self._job_count()
        resp = self.url_open(
            self._url(),
            data=json.dumps(payload),
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": "WRONG"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._job_count(), before)

    def test_unknown_uuid_returns_200(self):
        payload = {"update_id": 902, "message": {
            "message_id": 3, "date": 1700000002,
            "from": {"id": 79, "first_name": "Cara", "username": "cara"},
            "chat": {"id": 79, "type": "private"}, "text": "Hi"}}
        before = self._job_count()
        url = f"/omnichannel/webhook/telegram/{uuid.uuid4().hex}"
        resp = self.url_open(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": "S"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._job_count(), before)

    def test_malformed_body_returns_200(self):
        before = self._job_count()
        resp = self.url_open(
            self._url(),
            data=b"{ this is not json",
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": "S"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._job_count(), before)
