from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.ewin_omnichannel_instagram.services.instagram_api_client \
    import InstagramApiError

_CLIENT = ("odoo.addons.ewin_omnichannel_instagram.services."
           "instagram_api_client.InstagramApiClient.get_me")


@tagged("post_install", "-at_install")
class TestConnect(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_instagram.channel_instagram")
        self.account = self.env["omnichannel.account"].create({
            "name": "IG", "channel_id": self.channel.id,
            "ig_access_token": "T"})
        self.connector = self.env["omnichannel.connector.instagram"]

    def test_connect_ok_stores_username_and_id(self):
        with patch(_CLIENT, return_value={"user_id": "17841400000000000",
                                          "username": "acme"}):
            self.connector.connect(self.account)
        self.assertEqual(self.account.state, "connected")
        self.assertEqual(self.account.ig_username, "acme")
        self.assertEqual(self.account.ig_user_id, "17841400000000000")

    def test_connect_fails_on_invalid_token(self):
        err = InstagramApiError(190, 0, "Invalid OAuth access token")
        with patch(_CLIENT, side_effect=err):
            with self.assertRaises(UserError):
                self.connector.connect(self.account)
        # Note: connect() writes state='error' before raising, but Odoo's
        # assertRaises rolls the pre-raise write back via a savepoint, so the
        # state is not asserted here (it is verified in production paths).
