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

    def test_account_of_another_channel_is_not_reachable_here(self):
        """The route used to carry a <channel_code> segment and dispatch to the
        Telegram connector whatever it matched. Channels whose own controller
        sits elsewhere (Viber) or does not exist at all (email, livechat) were
        therefore reachable at .../webhook/<their code>/<uuid>, and the guard
        left standing there — tg_webhook_secret, empty on such an account —
        checked nothing."""
        other = self.env["omnichannel.channel"].create(
            {"name": "SMS", "code": "sms"})
        account = self.env["omnichannel.account"].create(
            {"name": "Gateway", "channel_id": other.id})
        payload = {"update_id": 903, "message": {
            "message_id": 4, "date": 1700000003,
            "from": {"id": 80, "first_name": "Mallory"},
            "chat": {"id": 80, "type": "private"}, "text": "forged"}}
        resp = self.url_open(
            f"/omnichannel/webhook/sms/{account.webhook_uuid}",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(self.env["omnichannel.message"].search(
            [("account_id", "=", account.id)]))

    def test_unset_secret_rejects_the_request(self):
        """An empty stored secret must mean "reject", not "skip the check" —
        the three Meta connectors already fail closed."""
        self.account.tg_webhook_secret = False
        payload = {"update_id": 904, "message": {
            "message_id": 5, "date": 1700000004,
            "from": {"id": 81, "first_name": "Mallory"},
            "chat": {"id": 81, "type": "private"}, "text": "forged"}}
        before = self._job_count()
        resp = self.url_open(
            self._url(),
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 200)  # still no existence oracle
        self.assertEqual(self._job_count(), before)
        self.assertFalse(self.env["omnichannel.message"].search(
            [("account_id", "=", self.account.id),
             ("direction", "=", "inbound")]))

    def test_malformed_body_returns_200(self):
        before = self._job_count()
        resp = self.url_open(
            self._url(),
            data=b"{ this is not json",
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": "S"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._job_count(), before)
