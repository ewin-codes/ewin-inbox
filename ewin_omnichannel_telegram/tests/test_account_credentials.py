from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMaskedCredential(TransactionCase):
    """tg_bot_token_masked is what the operator group sees where the admin
    group sees tg_bot_token itself. The compute behind it must not need the
    access it exists to stand in for: the account form shows exactly one
    of the two fields to exactly one of the two groups, so a compute that
    reads the credential unprivileged turns the whole form into an
    AccessError for every operator.
    """

    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_telegram.channel_telegram")
        self.account = self.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": self.channel.id,
            "tg_bot_token": "123:ABC"})
        self.operator = self.env["res.users"].create({
            "name": "Operator", "login": "tg_masked_operator",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        # A cold cache, the way the operator's own request starts. Odoo's
        # field cache is shared by every environment of a transaction and
        # is not keyed by user, so a value this fixture just wrote would
        # otherwise be handed to the operator without an access check -
        # and the test would pass whether or not the compute can read it.
        self.env.invalidate_all()

    def test_the_operator_reads_the_mask(self):
        self.assertEqual(
            self.account.with_user(self.operator).tg_bot_token_masked,
            "***************")

    def test_the_operator_still_cannot_read_the_credential(self):
        with self.assertRaises(AccessError):
            self.account.with_user(self.operator).tg_bot_token  # noqa: B018

    def test_an_unset_credential_masks_to_nothing(self):
        self.account.tg_bot_token = False
        self.env.invalidate_all()
        self.assertEqual(
            self.account.with_user(self.operator).tg_bot_token_masked, "")
