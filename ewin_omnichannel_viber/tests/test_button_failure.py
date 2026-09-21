from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.ewin_omnichannel_viber.services.viber_api_client import (
    ViberApiError)

_CALL = ("odoo.addons.ewin_omnichannel_viber.services."
         "viber_api_client.ViberApiClient.get_account_info")


@tagged("post_install", "-at_install")
class TestButtonFailure(TransactionCase):
    """A provider failure on an account button reports itself and stays.

    The failure path records what went wrong on the account - the error
    state and ``last_error`` - and Odoo commits a request only when it
    returns successfully. Reporting the failure by raising would roll that
    record back with the rest of the request: the user would read the
    message, and the form behind it would come back looking untouched by
    a failure they had just been told about.
    """

    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_viber.channel_viber")
        self.account = self.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": self.channel.id,
            "viber_auth_token": "T"})
        self.connector = self.env["omnichannel.connector.viber"]
        self.failure = ViberApiError(1, "invalidAuthToken", retriable=False)

    def test_a_provider_failure_is_a_sticky_danger_toast(self):
        with patch(_CALL, side_effect=self.failure):
            action = self.connector.connect(self.account)
        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(action["params"]["type"], "danger")
        self.assertTrue(action["params"]["sticky"])

    def test_a_provider_failure_survives_the_request(self):
        with patch(_CALL, side_effect=self.failure):
            self.connector.connect(self.account)
        self.assertEqual(self.account.state, "error")
        self.assertTrue(self.account.sudo().last_error)

    def test_webhook_status_reports_a_refusal_too(self):
        """Every button that calls Viber answers the same way.

        This one used to let the provider exception escape raw, which
        Odoo shows as a traceback dialog and which rolls the request back
        - so the account kept whatever webhook status it had before.
        """
        with patch(_CALL, side_effect=self.failure):
            action = self.connector.viber_webhook_info(self.account)
        self.assertEqual(action["params"]["type"], "danger")
        self.assertEqual(self.account.state, "error")
        self.assertTrue(self.account.sudo().last_error)
