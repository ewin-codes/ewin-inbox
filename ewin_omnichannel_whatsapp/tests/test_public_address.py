from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPublicAddress(TransactionCase):
    """The address a notification names as the one the customer wrote to."""

    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_whatsapp.channel_whatsapp")

    def test_the_business_phone_is_the_address(self):
        account = self.env["omnichannel.account"].create({
            "name": "WA", "channel_id": self.channel.id,
            "wa_business_phone": "+380 93 955 08 89"})
        self.assertEqual(account._get_public_address(), "+380 93 955 08 89")

    def test_no_business_phone_gives_an_empty_address(self):
        account = self.env["omnichannel.account"].create({
            "name": "WA", "channel_id": self.channel.id})
        self.assertEqual(account._get_public_address(), "")
