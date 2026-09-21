import datetime
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.ewin_omnichannel_instagram.services.instagram_api_client \
    import InstagramApiError

_REFRESH = ("odoo.addons.ewin_omnichannel_instagram.services."
            "instagram_api_client.InstagramApiClient.refresh_long_lived_token")


@tagged("post_install", "-at_install")
class TestTokenRefresh(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_instagram.channel_instagram")
        self.connector = self.env["omnichannel.connector.instagram"]

    def _account(self, name="IG", token="OLD", expires_at=None):
        vals = {"name": name, "channel_id": self.channel.id,
                "ig_access_token": token}
        if expires_at is not None:
            vals["ig_token_expires_at"] = expires_at
        return self.env["omnichannel.account"].create(vals)

    def test_pasting_token_seeds_60_day_expiry(self):
        account = self._account()
        expiry = account.sudo().ig_token_expires_at
        self.assertTrue(expiry)
        now = fields.Datetime.now()
        self.assertGreater(expiry, now + datetime.timedelta(days=59))
        self.assertLess(expiry, now + datetime.timedelta(days=61))

    def test_refresh_updates_token_and_expiry(self):
        account = self._account()
        with patch(_REFRESH, return_value={
                "access_token": "NEW", "token_type": "bearer",
                "expires_in": 5184000}):  # 60 days
            ok = self.connector.refresh_token(account)
        self.assertTrue(ok)
        self.assertEqual(account.sudo().ig_access_token, "NEW")
        self.assertGreater(account.sudo().ig_token_expires_at,
                           fields.Datetime.now() + datetime.timedelta(days=59))

    def test_refresh_failure_flips_to_error(self):
        account = self._account()
        err = InstagramApiError(190, 0, "Token expired", retriable=False)
        with patch(_REFRESH, side_effect=err):
            ok = self.connector.refresh_token(account)
        self.assertFalse(ok)
        self.assertEqual(account.state, "error")
        self.assertTrue(account.last_error)

    def test_cron_only_refreshes_near_expiry(self):
        now = fields.Datetime.now()
        near = self._account(
            name="near", expires_at=now + datetime.timedelta(days=3))
        far = self._account(
            name="far", expires_at=now + datetime.timedelta(days=45))
        called = []
        original = type(self.connector).refresh_token

        def _spy(self, account):
            called.append(account.id)
            return True

        with patch.object(type(self.connector), "refresh_token", _spy):
            self.env["omnichannel.account"]._cron_ig_refresh_tokens()
        self.assertIn(near.id, called)
        self.assertNotIn(far.id, called)
        self.assertIs(type(self.connector).refresh_token, original)

    def test_the_button_reports_a_refusal_and_leaves_the_reason(self):
        """The manual Refresh Token button.

        refresh_token records the reason on the account and returns False
        rather than raising, because raising would roll that record back
        with the request - the journal row included. The button reads it
        back and shows it.
        """
        account = self._account(name="button")
        err = InstagramApiError(190, 0, "Token expired", retriable=False)
        with patch(_REFRESH, side_effect=err):
            action = account.action_ig_refresh_token()
        self.assertEqual(action["params"]["type"], "danger")
        self.assertEqual(account.state, "error")
        self.assertTrue(account.sudo().last_error)
        self.assertTrue(self.env["omnichannel.error.log"].search(
            [("account_id", "=", account.id)]))

    def test_the_button_confirms_a_refresh(self):
        account = self._account(name="button_ok")
        with patch(_REFRESH, return_value={
                "access_token": "NEW", "expires_in": 5184000}):
            action = account.action_ig_refresh_token()
        self.assertEqual(action["params"]["type"], "success")
        self.assertEqual(account.sudo().ig_access_token, "NEW")

