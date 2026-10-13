from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOutbound(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_whatsapp.channel_whatsapp")
        self.account = self.env["omnichannel.account"].create({
            "name": "WA", "channel_id": self.channel.id,
            "wa_phone_number_id": "PN1", "wa_access_token": "T"})
        self.identity = self.env["omnichannel.identity"].create({
            "account_id": self.account.id, "external_id": "15551230000"})
        self.conversation = self.env["omnichannel.conversation"].create({
            "account_id": self.account.id, "identity_id": self.identity.id})

    def _msg(self, body="reply"):
        return self.env["omnichannel.message"].create({
            "conversation_id": self.conversation.id, "direction": "outbound",
            "sender_type": "operator", "message_type": "text", "body": body,
            "state": "queued"})

    def test_send_text_marks_sent(self):
        connector = self.env["omnichannel.connector.whatsapp"]
        msg = self._msg("hello there")
        with patch("odoo.addons.ewin_omnichannel_whatsapp.services."
                   "whatsapp_api_client.WhatsAppApiClient.send_text",
                   return_value={"messages": [{"id": "wamid.OUT"}]}):
            connector.send_message(self.account, msg)
        self.assertEqual(msg.state, "sent")
        self.assertEqual(msg.external_message_id, "wamid.OUT")
        self.assertTrue(msg.sent_at)

    def test_window_error_raises_non_retriable(self):
        from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
            import NonRetriableError
        from odoo.addons.ewin_omnichannel_whatsapp.services.whatsapp_api_client \
            import WhatsAppApiError
        connector = self.env["omnichannel.connector.whatsapp"]
        msg = self._msg("late reply")
        err = WhatsAppApiError(131047, 0, "Re-engagement", retriable=False)
        with patch("odoo.addons.ewin_omnichannel_whatsapp.services."
                   "whatsapp_api_client.WhatsAppApiClient.send_text",
                   side_effect=err):
            with self.assertRaises(NonRetriableError):
                connector.send_message(self.account, msg)

    def test_a_friendly_error_reaches_the_log_already_translated(self):
        """The friendly texts are module-level _lt terms. Passed on lazy,
        they are resolved deep inside the ORM, where no environment is in
        reach: the operator gets the English source and the server log a
        "no translation language detected" warning for every failed send."""
        from odoo.addons.ewin_omnichannel_whatsapp.services.whatsapp_api_client \
            import WhatsAppApiError
        connector = self.env["omnichannel.connector.whatsapp"]
        with self.assertNoLogs("odoo.tools.translate", "WARNING"):
            summary = connector.handle_provider_error(
                self.account,
                WhatsAppApiError(131047, 0, "Re-engagement", retriable=False))
        self.assertIsInstance(summary, str)

    def test_a_friendly_status_error_is_translated(self):
        """A failed-delivery status takes the same _lt table."""
        connector = self.env["omnichannel.connector.whatsapp"]
        self.assertIsInstance(
            connector._friendly_status_error({"code": 131047}), str)
