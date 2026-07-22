from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.ewin_omnichannel_messenger.services.messenger_api_client \
    import MessengerApiError

_CLIENT = ("odoo.addons.ewin_omnichannel_messenger.services."
           "messenger_api_client.MessengerApiClient.get_page")


@tagged("post_install", "-at_install")
class TestConnect(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_messenger.channel_messenger")
        self.account = self.env["omnichannel.account"].create({
            "name": "MG", "channel_id": self.channel.id, "mg_page_id": "PAGE1",
            "mg_page_access_token": "T"})
        self.connector = self.env["omnichannel.connector.messenger"]

    def test_connect_ok_sets_page_name(self):
        with patch(_CLIENT, return_value={"name": "Acme Page"}):
            self.connector.connect(self.account)
        self.assertEqual(self.account.state, "connected")
        self.assertEqual(self.account.mg_page_name, "Acme Page")

    def test_connect_tolerates_missing_metadata_permission(self):
        # Reading the Page name needs pages_read_engagement; a 100/200 there
        # must not fail the health check — the token is still messaging-capable.
        err = MessengerApiError(100, 0, "requires pages_read_engagement")
        with patch(_CLIENT, side_effect=err):
            self.connector.connect(self.account)
        self.assertEqual(self.account.state, "connected")
        self.assertFalse(self.account.mg_page_name)

    def test_connect_fails_on_invalid_token(self):
        err = MessengerApiError(190, 0, "Invalid OAuth access token")
        with patch(_CLIENT, side_effect=err):
            with self.assertRaises(UserError):
                self.connector.connect(self.account)
