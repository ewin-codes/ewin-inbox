from odoo.tests import tagged
from psycopg2 import IntegrityError
from odoo.tools import mute_logger
from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestIdentity(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})

    def test_identity_unique_per_account(self):
        self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "123"})
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.env["omnichannel.identity"].create(
                {"account_id": self.account.id, "external_id": "123"})

    def test_identity_company_from_account(self):
        ident = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "123"})
        self.assertEqual(ident.company_id, self.account.company_id)
