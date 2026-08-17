from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

SET_WEBHOOK = ("odoo.addons.ewin_omnichannel_telegram.services."
               "telegram_api_client.TelegramApiClient.set_webhook")


@tagged("post_install", "-at_install")
class TestTelegramAccountActions(TransactionCase):
    """The account buttons administer the channel: they connect, register
    webhooks and write credentials the operator group may not even read. The
    menu they live in is admin-only, which is presentation — ``call_button``
    reaches any public method on a model the caller can read, and operators
    hold read on ``omnichannel.account``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_telegram.channel_telegram")
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": cls.channel.id, "tg_bot_token": "T"})
        cls.operator = cls._user("tg_action_operator", "group_omni_operator")
        cls.admin = cls._user("tg_action_admin", "group_omni_admin")

    @classmethod
    def _user(cls, login, group):
        return cls.env["res.users"].create({
            "name": login, "login": login,
            "groups_id": [(4, cls.env.ref(
                f"ewin_omnichannel_core.{group}").id)]})

    def test_operator_cannot_register_the_webhook(self):
        with patch(SET_WEBHOOK) as set_webhook:
            with self.assertRaises(AccessError):
                self.account.with_user(
                    self.operator).action_tg_register_webhook()
        self.assertFalse(set_webhook.called)

    def test_operator_cannot_remove_the_webhook(self):
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.delete_webhook") as rm:
            with self.assertRaises(AccessError):
                self.account.with_user(self.operator).action_tg_remove_webhook()
        self.assertFalse(rm.called)

    def test_admin_can_register_the_webhook(self):
        with patch(SET_WEBHOOK) as set_webhook:
            self.account.with_user(self.admin).action_tg_register_webhook()
        self.assertTrue(set_webhook.called)
