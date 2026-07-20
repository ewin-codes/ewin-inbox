from odoo.tests import tagged
from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestMultiCompany(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.company_b = self.env["res.company"].create({"name": "Company B"})
        self.account_a = self.env["omnichannel.account"].create(
            {"name": "A", "channel_id": self.channel.id, "company_id": self.company.id})
        self.account_b = self.env["omnichannel.account"].create(
            {"name": "B", "channel_id": self.channel.id, "company_id": self.company_b.id})
        ident_b = self.env["omnichannel.identity"].create(
            {"account_id": self.account_b.id, "external_id": "9"})
        self.conv_b = self.env["omnichannel.conversation"].create(
            {"name": "cb", "account_id": self.account_b.id, "identity_id": ident_b.id})
        self.operator = self.env["res.users"].create({
            "name": "Op A", "login": "op_a",
            "company_id": self.company.id, "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        self.team_b = self.env["omnichannel.team"].create(
            {"name": "Team B", "company_id": self.company_b.id})

    def test_operator_cannot_see_other_company_conversation(self):
        convs = self.env["omnichannel.conversation"].with_user(
            self.operator).search([])
        self.assertNotIn(self.conv_b, convs)

    def test_operator_cannot_see_other_company_team(self):
        teams = self.env["omnichannel.team"].with_user(
            self.operator).search([])
        self.assertNotIn(self.team_b, teams)
