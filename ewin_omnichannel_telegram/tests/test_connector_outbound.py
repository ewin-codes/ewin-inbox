from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.ewin_omnichannel_telegram.services.telegram_api_client \
    import TelegramApiError


@tagged("post_install", "-at_install")
class TestConnectorOutbound(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_telegram.channel_telegram")
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": cls.channel.id, "tg_bot_token": "T"})
        cls.identity = cls.env["omnichannel.identity"].create(
            {"account_id": cls.account.id, "external_id": "555"})
        cls.conv = cls.env["omnichannel.conversation"].create({
            "name": "c", "account_id": cls.account.id,
            "identity_id": cls.identity.id})
        cls.connector = cls.env["omnichannel.connector.telegram"]

    def test_send_success_sets_sent(self):
        msg = self.env["omnichannel.message"].create({
            "conversation_id": self.conv.id, "direction": "outbound",
            "sender_type": "operator", "body": "Reply", "state": "queued"})
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message",
                   return_value={"message_id": 42}):
            self.connector.send_message(self.account, msg)
        self.assertEqual(msg.state, "sent")
        self.assertEqual(msg.external_message_id, "42")

    def test_blocked_user_non_retriable(self):
        # NOTE: intentionally NOT using self.assertRaises() here. Odoo's
        # TransactionCase.assertRaises wraps its block in a cr.savepoint()
        # that gets rolled back once the expected exception is caught, which
        # would silently undo the error-log row written just before the
        # raise. A plain try/except keeps that row visible for the assertion
        # below, matching what really happens in production (the job queue
        # catches NonRetriableError without rolling back the transaction).
        from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
            import NonRetriableError
        msg = self.env["omnichannel.message"].create({
            "conversation_id": self.conv.id, "direction": "outbound",
            "sender_type": "operator", "body": "Reply", "state": "queued"})
        err = TelegramApiError(403, "Forbidden: bot was blocked by the user",
                               retriable=False)
        raised = False
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message",
                   side_effect=err):
            try:
                self.connector.send_message(self.account, msg)
            except NonRetriableError:
                raised = True
        self.assertTrue(raised, "NonRetriableError was not raised")
        log = self.env["omnichannel.error.log"].search(
            [("account_id", "=", self.account.id)], limit=1)
        self.assertTrue(log)

    def test_send_outbound_retriable_error_leaves_message_queued(self):
        # A retriable TelegramApiError must NOT flip the message to "failed" —
        # the job queue will retry it and it may well succeed. See routing_service
        # .send_outbound: only NonRetriableError marks the message failed.
        routing = self.env["omnichannel.routing.service"]
        msg = self.env["omnichannel.message"].create({
            "conversation_id": self.conv.id, "direction": "outbound",
            "sender_type": "operator", "body": "Reply", "state": "queued"})
        err = TelegramApiError(429, "Too Many Requests", retriable=True)
        raised = False
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message",
                   side_effect=err):
            try:
                routing.send_outbound(msg.id)
            except TelegramApiError:
                raised = True
        self.assertTrue(raised, "the retriable error was not propagated to the job")
        self.assertEqual(msg.state, "queued")

    def test_send_outbound_non_retriable_error_marks_failed(self):
        routing = self.env["omnichannel.routing.service"]
        from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
            import NonRetriableError
        msg = self.env["omnichannel.message"].create({
            "conversation_id": self.conv.id, "direction": "outbound",
            "sender_type": "operator", "body": "Reply", "state": "queued"})
        err = TelegramApiError(403, "Forbidden: bot was blocked by the user",
                               retriable=False)
        raised = False
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message",
                   side_effect=err):
            try:
                routing.send_outbound(msg.id)
            except NonRetriableError:
                raised = True
        self.assertTrue(raised, "NonRetriableError was not propagated to the job")
        self.assertEqual(msg.state, "failed")
