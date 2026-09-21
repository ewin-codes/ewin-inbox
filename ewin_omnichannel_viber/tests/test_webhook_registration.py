from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..services.viber_api_client import ViberApiError

SET_WEBHOOK_PATH = ("odoo.addons.ewin_omnichannel_viber.services."
                    "viber_api_client.ViberApiClient.set_webhook")
ISOLATED_WRITE_PATH = ("odoo.addons.ewin_omnichannel_core.models."
                       "omnichannel_account.OmnichannelAccount."
                       "_write_isolated")


@tagged("post_install", "-at_install")
class TestViberWebhookRegistration(TransactionCase):
    """Registering the webhook must survive Viber's validation callback.

    Viber only confirms ``set_webhook`` after POSTing an ``{"event":
    "webhook"}`` callback to the URL and getting a 200 back. That callback is a
    separate request which commits ``last_webhook_at`` on the account row, so a
    plain write afterwards raises ``could not serialize access due to
    concurrent update``. Odoo then retries the whole request, the retry calls
    Viber again, Viber calls back again — the conflict repeats until the
    retries run out and the registration result is dropped, even though Viber
    accepted it.

    These tests assert the mechanism rather than the stored value: a test
    transaction is never committed, so the account row does not exist for the
    separate connection ``_write_isolated`` opens and the write there lands on
    no rows. What can be pinned down is that the result leaves the request
    cursor, and with which values.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_viber.channel_viber")
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": cls.channel.id,
            "viber_auth_token": "T"})
        cls.connector = cls.env["omnichannel.connector.viber"]

    def test_register_webhook_sends_url_and_subscribes_to_messages(self):
        with patch(SET_WEBHOOK_PATH, return_value={"status": 0}) as mock_set:
            self.connector.register_webhook(self.account)
        url, event_types = mock_set.call_args[0]
        self.assertEqual(url, self.connector._webhook_url(self.account))
        self.assertIn("message", event_types)

    def test_successful_registration_is_written_out_of_band(self):
        with patch(SET_WEBHOOK_PATH, return_value={"status": 0}), \
                patch(ISOLATED_WRITE_PATH) as mock_write:
            self.connector.register_webhook(self.account)
        mock_write.assert_called_once_with({
            "viber_webhook_status": "registered", "state": "connected"})

    def test_failed_registration_is_written_out_of_band(self):
        with patch(SET_WEBHOOK_PATH, side_effect=ViberApiError(
                1, "webhookUrlInvalid", retriable=False)), \
                patch(ISOLATED_WRITE_PATH) as mock_write:
            action = self.connector.register_webhook(self.account)
        self.assertEqual(action["params"]["type"], "danger")
        mock_write.assert_called_once_with({
            "state": "error", "last_error": "webhookUrlInvalid"})

    def test_registration_never_writes_the_account_on_the_request_cursor(self):
        """The request transaction is the one the callback races; it must stay
        out of the account row entirely."""
        registry = self.env.registry
        opened = []
        original_cursor = type(registry).cursor

        def counting_cursor(registry_self, /, *args, **kwargs):
            cursor = original_cursor(registry_self, *args, **kwargs)
            opened.append(cursor)
            return cursor

        with patch(SET_WEBHOOK_PATH, return_value={"status": 0}), \
                patch.object(type(registry), "cursor", counting_cursor):
            self.connector.register_webhook(self.account)

        self.assertEqual(len(opened), 1, "expected exactly one isolated write")
        # nothing reached the account through the request transaction
        self.assertFalse(self.account.viber_webhook_status)
        self.assertEqual(self.account.state, "draft")
