from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from ..services.notify_api_client import (
    TelegramNotifyClient, TelegramNotifyError, escape_html, redact_token)
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

    def test_a_second_company_may_have_its_own_notifier(self):
        company_b = self.env["res.company"].create({"name": "Notify Co B"})
        admin_b = self.env["res.users"].create({
            "name": "Admin B", "login": "notify_admin_b",
            "company_id": company_b.id,
            "company_ids": [(6, 0, [company_b.id])],
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_admin").id)]})
        notifier_b = self.env["omnichannel.telegram.notifier"].with_user(
            admin_b).create({"name": "B", "company_id": company_b.id})
        self.assertTrue(notifier_b.id)
        # rule_notifier_company: admin_b's own notifier is visible to them,
        # company A's (self.notifier) is not.
        visible = self.env["omnichannel.telegram.notifier"].with_user(
            admin_b).search([])
        self.assertIn(notifier_b, visible)
        self.assertNotIn(self.notifier, visible)

    def test_the_constraint_still_refuses_a_same_company_duplicate_across_scopes(self):
        # _check_one_active_per_company's own search must not be blinded by
        # rule_notifier_company: even when the duplicate is created through a
        # user whose company_ids does not include the target company (here,
        # by way of an elevated call, the way a migration or an internal
        # service might reach this model), the twin already sitting in that
        # company must still be found and the create refused.
        company_b = self.env["res.company"].create({"name": "Notify Co B"})
        admin_b = self.env["res.users"].create({
            "name": "Admin B", "login": "notify_admin_b2",
            "company_id": company_b.id,
            "company_ids": [(6, 0, [company_b.id])],
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_admin").id)]})
        with self.assertRaises(ValidationError):
            self.env["omnichannel.telegram.notifier"].with_user(
                admin_b).sudo().create({
                    "name": "Duplicate", "company_id": self.company.id})

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

    def test_a_non_json_response_is_translated_and_retriable(self):
        # A proxy or captive portal can answer with an HTML page instead of
        # JSON. response.json() must be caught in the same guarded region as
        # the request itself, or this reaches the caller as a bare
        # JSONDecodeError instead of a TelegramNotifyError.
        from unittest.mock import MagicMock, patch
        response = MagicMock()
        response.content = b"<html>Bad Gateway</html>"
        response.status_code = 502
        response.json.side_effect = ValueError(
            "Expecting value: line 1 column 1 (char 0)")
        with patch("requests.post", return_value=response):
            with self.assertRaises(TelegramNotifyError) as cm:
                TelegramNotifyClient("BOT-TOKEN").get_me()
        self.assertTrue(cm.exception.retriable)
        self.assertIn("502", cm.exception.description)
        self.assertNotIn("Bad Gateway", cm.exception.description)

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

    def test_check_connection_refuses_an_operator(self):
        # An operator holds only read access (ir.model.access.csv). The
        # button's own check_access("write") is the only thing standing
        # between that read grant and the sudo() write inside it — nothing
        # else in the stack enforces it, since call_button reaches any
        # button on a model the caller can read.
        operator = self.env["res.users"].create({
            "name": "Restricted Operator", "login": "notify_btn_operator_1",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        with self.assertRaises(AccessError):
            self.notifier.with_user(operator).action_check_connection()

    def test_register_webhook_refuses_an_operator(self):
        operator = self.env["res.users"].create({
            "name": "Restricted Operator", "login": "notify_btn_operator_2",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        with self.assertRaises(AccessError):
            self.notifier.with_user(operator).action_register_webhook()

    def test_remove_webhook_refuses_an_operator(self):
        operator = self.env["res.users"].create({
            "name": "Restricted Operator", "login": "notify_btn_operator_3",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        with self.assertRaises(AccessError):
            self.notifier.with_user(operator).action_remove_webhook()

    def test_remove_webhook_records_a_provider_error(self):
        self.notifier.webhook_status = "registered"
        client = self._fake_client()
        client.delete_webhook.side_effect = TelegramNotifyError(
            401, "Unauthorized", retriable=False)
        with self._with_client(client):
            action = self.notifier.action_remove_webhook()
        self.assertEqual(action["params"]["type"], "danger")
        # This button records no state on failure — unlike the other two,
        # it never calls _set_error() — so the only thing to check is that
        # the write past the try/except did not run either.
        self.assertEqual(self.notifier.webhook_status, "registered",
                          "a failed removal must not mark the webhook removed")
