from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from ..services.notify_api_client import (
    TelegramNotifyError, escape_html, redact_token)
from .common import NotifyCase


@tagged("post_install", "-at_install")
class TestNotifier(NotifyCase):

    def test_webhook_url_is_built_from_base_url(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://example.test")
        self.assertEqual(
            self.notifier._webhook_url(),
            f"https://example.test/omnichannel/notify/telegram/"
            f"{self.notifier.webhook_uuid}")

    def test_one_active_notifier_per_company(self):
        with self.assertRaises(ValidationError):
            self.env["omnichannel.telegram.notifier"].create({
                "name": "Second", "company_id": self.company.id})

    def test_archived_notifier_leaves_room_for_another(self):
        self.notifier.active = False
        twin = self.env["omnichannel.telegram.notifier"].create({
            "name": "Second", "company_id": self.company.id})
        self.assertTrue(twin.id)

    def test_for_company_returns_only_the_active_one(self):
        Notifier = self.env["omnichannel.telegram.notifier"]
        self.assertEqual(Notifier._for_company(self.company), self.notifier)
        self.notifier.active = False
        self.assertFalse(Notifier._for_company(self.company))

    def test_token_is_masked_for_everyone_else(self):
        self.assertEqual(self.notifier.bot_token_masked, "***************")

    def test_token_is_masked_without_read_access_to_the_token_field(self):
        # bot_token_masked is what an operator — no admin group, so no
        # access to bot_token itself — sees on the same form. The compute
        # must not need the access it exists to stand in for.
        operator = self.env["res.users"].create({
            "name": "Operator", "login": "notify_operator",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        self.assertEqual(
            self.notifier.with_user(operator).bot_token_masked,
            "***************")

    def test_negative_throttle_is_refused(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.notifier.throttle_minutes = -1
            self.notifier.flush_recordset(["throttle_minutes"])

    def test_redact_token_hides_the_credential(self):
        text = "POST https://api.telegram.org/bot123:ABC/sendMessage failed"
        self.assertNotIn("123:ABC", redact_token(text))
        self.assertIn("/bot***", redact_token(text))

    def test_escape_html_touches_three_characters_only(self):
        self.assertEqual(escape_html('a & b < c > d "e"'),
                         'a &amp; b &lt; c &gt; d "e"')

    def test_friendly_message_for_a_revoked_token(self):
        error = TelegramNotifyError(401, "Unauthorized", retriable=False)
        self.assertIn("invalid", str(self.notifier._friendly(error)).lower())

    def test_check_connection_stores_the_bot_identity(self):
        client = self._fake_client()
        with self._with_client(client):
            self.notifier.action_check_connection()
        self.assertEqual(self.notifier.bot_username, "ewin_notify_bot")
        self.assertEqual(self.notifier.bot_external_id, "1")
        self.assertEqual(self.notifier.state, "connected")
        self.assertFalse(self.notifier.last_error)

    def test_check_connection_records_a_bad_token(self):
        client = self._fake_client()
        client.get_me.side_effect = TelegramNotifyError(
            401, "Unauthorized", retriable=False)
        with self._with_client(client):
            action = self.notifier.action_check_connection()
        self.assertEqual(action["params"]["type"], "danger")
        self.assertEqual(self.notifier.state, "error")
        self.assertIn("Unauthorized", self.notifier.last_error)

    def test_register_webhook_records_a_provider_error(self):
        client = self._fake_client()
        client.set_webhook.side_effect = TelegramNotifyError(
            401, "Unauthorized", retriable=False)
        with self._with_client(client):
            action = self.notifier.action_register_webhook()
        self.assertEqual(action["params"]["type"], "danger")
        self.assertEqual(self.notifier.state, "error")
        self.assertIn("Unauthorized", self.notifier.last_error)

    def test_register_webhook_generates_a_secret_once(self):
        self.notifier.webhook_secret = False
        client = self._fake_client()
        with self._with_client(client):
            self.notifier.action_register_webhook()
        secret = self.notifier.webhook_secret
        self.assertTrue(secret)
        self.assertEqual(self.notifier.webhook_status, "registered")
        client.set_webhook.assert_called_once_with(
            self.notifier._webhook_url(), secret)
        with self._with_client(client):
            self.notifier.action_register_webhook()
        self.assertEqual(self.notifier.webhook_secret, secret,
                         "re-registering must keep the secret Telegram holds")

    def test_remove_webhook_marks_the_status(self):
        client = self._fake_client()
        with self._with_client(client):
            self.notifier.action_remove_webhook()
        self.assertEqual(self.notifier.webhook_status, "removed")
