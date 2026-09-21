from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import NotifyCase


@tagged("post_install", "-at_install")
class TestLinking(NotifyCase):

    def setUp(self):
        super().setUp()
        self.operator = self.env["res.users"].create({
            "name": "Olga Operator", "login": "olga_link_test",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})

    def test_link_action_returns_a_wizard_with_a_t_me_url(self):
        action = self.operator.with_user(self.operator).action_omni_tg_link()
        wizard = self.env["omnichannel.telegram.link"].browse(action["res_id"])
        self.assertTrue(wizard.url.startswith(
            "https://t.me/ewin_notify_bot?start="))
        self.assertEqual(wizard.user_id, self.operator)

    def test_link_action_stores_a_token_with_an_expiry(self):
        self.operator.with_user(self.operator).action_omni_tg_link()
        self.assertTrue(self.operator.sudo().omni_tg_link_token)
        self.assertGreater(self.operator.sudo().omni_tg_link_expires_at,
                           fields.Datetime.now())

    def test_a_colleague_cannot_issue_someone_elses_link(self):
        other = self.env["res.users"].create({
            "name": "Peter", "login": "peter_link_test",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        with self.assertRaises(AccessError):
            self.operator.with_user(other).action_omni_tg_link()

    def test_link_action_needs_a_connected_bot(self):
        self.notifier.bot_username = False
        with self.assertRaises(UserError):
            self.operator.with_user(self.operator).action_omni_tg_link()

    def test_consuming_a_token_returns_the_user_and_burns_it(self):
        self.operator.with_user(self.operator).action_omni_tg_link()
        token = self.operator.sudo().omni_tg_link_token
        Users = self.env["res.users"]
        self.assertEqual(Users._omni_tg_consume_link_token(token), self.operator)
        self.assertFalse(self.operator.sudo().omni_tg_link_token)
        self.assertFalse(Users._omni_tg_consume_link_token(token))

    def test_an_expired_token_is_refused_and_still_burned(self):
        self.operator.with_user(self.operator).action_omni_tg_link()
        token = self.operator.sudo().omni_tg_link_token
        self.operator.sudo().omni_tg_link_expires_at = fields.Datetime.subtract(
            fields.Datetime.now(), hours=1)
        self.assertFalse(
            self.env["res.users"]._omni_tg_consume_link_token(token))
        self.assertFalse(self.operator.sudo().omni_tg_link_token)

    def test_an_unknown_token_returns_nothing(self):
        self.assertFalse(
            self.env["res.users"]._omni_tg_consume_link_token("nope"))

    def test_unlink_clears_the_binding(self):
        self.operator.sudo().write({
            "omni_tg_chat_id": "555", "omni_tg_username": "olga"})
        self.operator.with_user(self.operator).action_omni_tg_unlink()
        self.assertFalse(self.operator.sudo().omni_tg_chat_id)
        self.assertFalse(self.operator.sudo().omni_tg_username)

    def test_an_operator_reads_their_own_binding_in_preferences(self):
        self.operator.sudo().omni_tg_chat_id = "555"
        mine = self.operator.with_user(self.operator)
        self.assertEqual(mine.read(["omni_tg_chat_id"])[0]["omni_tg_chat_id"],
                         "555")
