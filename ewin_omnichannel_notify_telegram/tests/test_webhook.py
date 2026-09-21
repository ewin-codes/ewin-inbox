import json
import uuid
from unittest.mock import patch

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestNotifyWebhook(HttpCase):

    def setUp(self):
        super().setUp()
        self.notifier = self.env["omnichannel.telegram.notifier"].create({
            "name": "Notifier", "bot_token": "BOT-TOKEN",
            "bot_username": "ewin_notify_bot", "webhook_secret": "SECRET"})
        self.operator = self.env["res.users"].create({
            "name": "Olga Operator", "login": "olga_webhook_test",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        self.admin_user = self.env["res.users"].create({
            "name": "Adam Admin", "login": "adam_webhook_test",
            "omni_tg_chat_id": "900",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_admin").id)]})
        self.patcher = patch.object(
            type(self.env["omnichannel.telegram.notifier"]), "_client")
        self.client = self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _url(self, notifier_uuid=None):
        return ("/omnichannel/notify/telegram/"
                f"{notifier_uuid or self.notifier.webhook_uuid}")

    def _post(self, payload, secret="SECRET", notifier_uuid=None):
        # The controller runs in its own request against the same test cursor;
        # anything still pending in the ORM cache would be invisible to it.
        self.env.flush_all()
        return self.url_open(
            self._url(notifier_uuid), data=json.dumps(payload),
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": secret})

    def _issue_token(self):
        self.operator.with_user(self.operator).action_omni_tg_link()
        return self.operator.sudo().omni_tg_link_token

    def _private(self, text, chat_id=555, from_id=555, username="olga"):
        return {"update_id": 1, "message": {
            "message_id": 1, "date": 1700000000,
            "from": {"id": from_id, "first_name": "Olga", "username": username},
            "chat": {"id": chat_id, "type": "private"}, "text": text}}

    def _group(self, text, chat_id=-100777, from_id=900):
        return {"update_id": 2, "message": {
            "message_id": 2, "date": 1700000001,
            "from": {"id": from_id, "first_name": "Adam"},
            "chat": {"id": chat_id, "type": "supergroup"}, "text": text}}

    def test_start_links_the_user_and_burns_the_token(self):
        token = self._issue_token()
        response = self._post(self._private(f"/start {token}"))
        self.assertEqual(response.status_code, 200)
        self.operator.invalidate_recordset()
        self.assertEqual(self.operator.sudo().omni_tg_chat_id, "555")
        self.assertEqual(self.operator.sudo().omni_tg_username, "olga")
        self.assertFalse(self.operator.sudo().omni_tg_link_token)

    def test_start_with_an_unknown_token_links_nobody(self):
        response = self._post(self._private("/start deadbeef"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.operator.sudo().omni_tg_chat_id)

    def test_bad_secret_is_a_silent_200(self):
        token = self._issue_token()
        response = self._post(self._private(f"/start {token}"), secret="WRONG")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.operator.sudo().omni_tg_chat_id)

    def test_unknown_uuid_is_a_silent_200(self):
        response = self._post(self._private("/start x"),
                              notifier_uuid=uuid.uuid4().hex)
        self.assertEqual(response.status_code, 200)

    def test_a_notifier_with_no_stored_secret_rejects_everything(self):
        self.notifier.sudo().webhook_secret = False
        token = self._issue_token()
        response = self._post(self._private(f"/start {token}"), secret="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.operator.sudo().omni_tg_chat_id)

    def test_register_from_an_admin_stores_the_group(self):
        response = self._post(self._group("/register"))
        self.assertEqual(response.status_code, 200)
        self.notifier.invalidate_recordset()
        self.assertEqual(self.notifier.group_chat_id, "-100777")

    def test_register_with_the_bot_suffix_is_accepted(self):
        self._post(self._group("/register@ewin_notify_bot"))
        self.notifier.invalidate_recordset()
        self.assertEqual(self.notifier.group_chat_id, "-100777")

    def test_register_from_a_stranger_is_ignored(self):
        self._post(self._group("/register", from_id=12345))
        self.notifier.invalidate_recordset()
        self.assertFalse(self.notifier.group_chat_id)

    def test_register_from_a_non_admin_is_ignored(self):
        self.operator.sudo().omni_tg_chat_id = "555"
        self._post(self._group("/register", from_id=555))
        self.notifier.invalidate_recordset()
        self.assertFalse(self.notifier.group_chat_id)

    def test_register_in_a_private_chat_is_ignored(self):
        self._post(self._private("/register", from_id=900, chat_id=900))
        self.notifier.invalidate_recordset()
        self.assertFalse(self.notifier.group_chat_id)

    def test_ordinary_chatter_is_ignored(self):
        response = self._post(self._private("hello there"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.operator.sudo().omni_tg_chat_id)

    def test_malformed_body_is_a_silent_200(self):
        response = self.url_open(
            self._url(), data="not json",
            headers={"Content-Type": "application/json",
                     "X-Telegram-Bot-Api-Secret-Token": "SECRET"})
        self.assertEqual(response.status_code, 200)
