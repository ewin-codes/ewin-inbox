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

    def _identity(self, **vals):
        return self.env["omnichannel.identity"].create(
            dict({"account_id": self.account.id, "external_id": "123"}, **vals))

    def test_handle_prefers_the_email_address(self):
        ident = self._identity(
            email="lena@example.com", username="lena", phone="+380671112233")
        self.assertEqual(ident.handle, "lena@example.com")

    def test_handle_falls_back_to_the_at_username(self):
        ident = self._identity(username="lena", phone="+380671112233")
        self.assertEqual(ident.handle, "@lena")

    def test_handle_falls_back_to_the_phone_number(self):
        ident = self._identity(phone="+380671112233")
        self.assertEqual(ident.handle, "+380671112233")

    def test_handle_falls_back_to_the_external_id(self):
        self.assertEqual(self._identity().handle, "123")

    def test_identity_service_stores_the_email_from_the_profile(self):
        ident = self.env["omnichannel.identity.service"].find_or_create(
            self.account, {"id": "lena@example.com", "name": "Lena",
                           "email": "lena@example.com"})
        self.assertEqual(ident.email, "lena@example.com")

    def test_conversation_exposes_the_identity_handle(self):
        ident = self._identity(email="lena@example.com")
        conv = self.env["omnichannel.conversation"].create(
            {"name": "Lena", "account_id": self.account.id,
             "identity_id": ident.id})
        self.assertEqual(conv.identity_handle, "lena@example.com")
