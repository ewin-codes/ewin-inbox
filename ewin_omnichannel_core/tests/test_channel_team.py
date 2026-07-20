from odoo.tests import tagged
from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestChannelTeam(OmnichannelCase):
    def test_channel_created_with_capabilities(self):
        self.assertEqual(self.channel.code, "test")
        self.assertTrue(self.channel.capabilities["text"])

    def test_channel_code_unique(self):
        from psycopg2 import IntegrityError
        from odoo.tools import mute_logger
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.env["omnichannel.channel"].create({"name": "Dup", "code": "test"})

    def test_team_defaults_company(self):
        team = self.env["omnichannel.team"].create({"name": "Support"})
        self.assertEqual(team.company_id, self.env.company)
