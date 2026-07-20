from unittest.mock import patch

from odoo.tests import tagged

from .common import OmnichannelCase

SEND_PATH = ("odoo.addons.ewin_omnichannel_telegram.services."
             "telegram_api_client.TelegramApiClient.send_message")


@tagged("post_install", "-at_install")
class TestReporting(OmnichannelCase):
    def setUp(self):
        super().setUp()
        # create_outbound delivers synchronously through a real connector, so
        # use the Telegram channel and mock the network call.
        self.tg_channel = self.env.ref(
            "ewin_omnichannel_telegram.channel_telegram", raise_if_not_found=False)
        if not self.tg_channel:
            self.skipTest("telegram module not installed")
        self.account = self.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": self.tg_channel.id, "tg_bot_token": "T"})
        self.identity = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "123"})
        self.conv = self.env["omnichannel.conversation"].create({
            "name": "Conv", "account_id": self.account.id,
            "identity_id": self.identity.id})

    def test_first_response_seconds_measured(self):
        svc = self.env["omnichannel.message.service"]
        svc.create_inbound(
            self.conv, {"text": "hi", "type": "text",
                        "external_message_id": "c1"})
        self.assertTrue(self.conv.first_customer_message_at)
        self.assertEqual(self.conv.first_response_seconds, 0)  # no reply yet
        self.conv.first_customer_message_at = "2026-01-01 10:00:00"
        with patch(SEND_PATH, return_value={"message_id": 7}):
            svc.create_outbound(self.conv, "hello")
        self.conv.first_operator_message_at = "2026-01-01 10:02:00"
        self.conv.invalidate_recordset(["first_response_seconds"])
        self.assertEqual(self.conv.first_response_seconds, 120)

    def test_first_operator_time_is_set_once(self):
        svc = self.env["omnichannel.message.service"]
        with patch(SEND_PATH, return_value={"message_id": 1}):
            svc.create_outbound(self.conv, "first")
            first = self.conv.first_operator_message_at
            self.assertTrue(first)
            svc.create_outbound(self.conv, "second")
        self.assertEqual(self.conv.first_operator_message_at, first)

    def test_internal_note_is_not_a_response(self):
        svc = self.env["omnichannel.message.service"]
        svc.create_outbound(self.conv, "note", is_internal=True)
        self.assertFalse(self.conv.first_operator_message_at)
