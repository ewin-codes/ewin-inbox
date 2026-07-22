from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOutbound(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_messenger.channel_messenger")
        self.account = self.env["omnichannel.account"].create({
            "name": "MG", "channel_id": self.channel.id, "mg_page_id": "PAGE1",
            "mg_page_access_token": "T"})
        self.identity = self.env["omnichannel.identity"].create({
            "account_id": self.account.id, "external_id": "USER1"})
        self.conversation = self.env["omnichannel.conversation"].create({
            "account_id": self.account.id, "identity_id": self.identity.id})

    def _msg(self, body="reply"):
        return self.env["omnichannel.message"].create({
            "conversation_id": self.conversation.id, "direction": "outbound",
            "sender_type": "operator", "message_type": "text", "body": body,
            "state": "queued"})

    def test_send_text_marks_sent(self):
        connector = self.env["omnichannel.connector.messenger"]
        msg = self._msg("hello there")
        with patch("odoo.addons.ewin_omnichannel_messenger.services."
                   "messenger_api_client.MessengerApiClient.send_text",
                   return_value={"message_id": "m_OUT",
                                 "recipient_id": "USER1"}):
            connector.send_message(self.account, msg)
        self.assertEqual(msg.state, "sent")
        self.assertEqual(msg.external_message_id, "m_OUT")
        self.assertTrue(msg.sent_at)

    def test_window_error_raises_non_retriable(self):
        from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
            import NonRetriableError
        from odoo.addons.ewin_omnichannel_messenger.services \
            .messenger_api_client import MessengerApiError
        connector = self.env["omnichannel.connector.messenger"]
        msg = self._msg("late reply")
        err = MessengerApiError(10, 2018278, "Outside window", retriable=False)
        with patch("odoo.addons.ewin_omnichannel_messenger.services."
                   "messenger_api_client.MessengerApiClient.send_text",
                   side_effect=err):
            with self.assertRaises(NonRetriableError):
                connector.send_message(self.account, msg)
