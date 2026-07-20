from unittest.mock import patch

import requests

from odoo.tests import TransactionCase, tagged

from odoo.addons.ewin_omnichannel_telegram.services.telegram_api_client import (
    TelegramApiClient,
    TelegramApiError,
)


@tagged("post_install", "-at_install")
class TestApiClientTokenRedaction(TransactionCase):
    def test_network_error_redacts_token(self):
        client = TelegramApiClient(
            token="123456:SECRETTOKEN", api_base_url="https://api.telegram.org")
        err_msg = (
            "HTTPSConnectionPool(host='api.telegram.org', port=443): "
            "Max retries exceeded with url: /bot123456:SECRETTOKEN/getMe")
        with patch("requests.post", side_effect=requests.ConnectionError(err_msg)):
            with self.assertRaises(TelegramApiError) as cm:
                client.get_me()
        self.assertNotIn("SECRETTOKEN", cm.exception.description)
        self.assertIn("/bot***", cm.exception.description)
