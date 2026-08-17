from unittest.mock import patch
from odoo.tests import tagged
from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestOutboundQueue(OmnichannelCase):
    def setUp(self):
        super().setUp()
        # requires telegram module installed for a real connector
        self.tg_channel = self.env.ref(
            "ewin_omnichannel_telegram.channel_telegram", raise_if_not_found=False)
        if not self.tg_channel:
            self.skipTest("telegram module not installed")
        self.account = self.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": self.tg_channel.id, "tg_bot_token": "T"})
        self.identity = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "1"})
        self.conv = self.env["omnichannel.conversation"].create({
            "name": "c", "account_id": self.account.id,
            "identity_id": self.identity.id})

    def test_outbound_reply_sends_immediately(self):
        # The first attempt is synchronous — no waiting for the cron.
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message",
                   return_value={"message_id": 7}) as mock_send:
            msg = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "Hello customer")
            self.assertTrue(mock_send.called)
        self.assertEqual(msg.state, "sent")
        self.assertEqual(msg.external_message_id, "7")
        # no job needed on immediate success
        self.assertFalse(self.env["omnichannel.job"].search(
            [("method", "=", "send_outbound")]))

    def test_outbound_retriable_error_falls_back_to_queue(self):
        from odoo.addons.ewin_omnichannel_telegram.services.telegram_api_client \
            import TelegramApiError
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message",
                   side_effect=TelegramApiError(500, "Server Error", retriable=True)):
            msg = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "reply")
        # sync send failed transiently -> message queued + a retry job enqueued
        self.assertEqual(msg.state, "queued")
        self.assertTrue(self.env["omnichannel.job"].search(
            [("method", "=", "send_outbound")]))

    def test_outbound_retry_exhaustion_marks_message_failed(self):
        from odoo.addons.ewin_omnichannel_telegram.services.telegram_api_client \
            import TelegramApiError
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message",
                   side_effect=TelegramApiError(
                       500, "Internal Server Error", retriable=True)):
            msg = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "reply")
            job = self.env["omnichannel.job"].search(
                [("method", "=", "send_outbound")], limit=1)
            self.assertTrue(job)
            job.max_retries = 1
            job.run()
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.retry_count, 1)
        self.assertEqual(msg.state, "failed")

    def test_outbound_mirror_author_is_operator(self):
        msg = self.env["omnichannel.message.service"].create_outbound(
            self.conv, "private note", is_internal=True)
        self.assertTrue(msg.mail_message_id)
        self.assertEqual(msg.mail_message_id.author_id, self.env.user.partner_id)

    def test_action_send_reply_reads_stored_composer(self):
        # composer_body is a stored field: the value set on the form survives the
        # object-button save/reload, so action_send_reply must see it and send.
        self.conv.write({"composer_body": "operator reply"})
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message",
                   return_value={"message_id": 9}):
            self.conv.action_send_reply()
        msg = self.env["omnichannel.message"].search(
            [("conversation_id", "=", self.conv.id), ("direction", "=", "outbound")],
            limit=1)
        self.assertTrue(msg)
        self.assertIn("operator reply", msg.body or "")
        self.assertEqual(msg.state, "sent")  # sent synchronously
        # composer cleared after send
        self.assertFalse(self.conv.composer_body)

    def test_operator_reply_in_discuss_forwards_to_telegram(self):
        # An operator typing directly in the linked Discuss channel is
        # forwarded to the customer through the connector.
        channel = self.conv._ensure_discuss_channel()
        operator = self.env["res.users"].create({
            "name": "Op", "login": "op_fwd_test",
            "email": "op_fwd@example.com",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message",
                   return_value={"message_id": 42}) as mock_send:
            mail_msg = channel.with_user(operator).message_post(
                body="Hi from operator", message_type="comment",
                subtype_xmlid="mail.mt_comment")
        self.assertTrue(mock_send.called)
        omni = self.env["omnichannel.message"].search(
            [("mail_message_id", "=", mail_msg.id)])
        self.assertEqual(len(omni), 1)
        self.assertEqual(omni.direction, "outbound")
        self.assertEqual(omni.state, "sent")

    def test_mirror_post_not_forwarded_twice(self):
        # our own outbound mirror carries omni_mirror context -> the channel
        # override must not create a second (duplicate) outbound message.
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message",
                   return_value={"message_id": 7}):
            msg = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "single reply")
        outbound = self.env["omnichannel.message"].search(
            [("conversation_id", "=", self.conv.id),
             ("direction", "=", "outbound")])
        self.assertEqual(len(outbound), 1)
        self.assertEqual(outbound, msg)

    def test_customer_mirror_not_forwarded(self):
        # an inbound message mirrored to the channel (customer author) must not
        # be forwarded back to Telegram.
        channel = self.conv._ensure_discuss_channel()
        partner = self.env["res.partner"].create({"name": "Cust"})
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message") as mock_send:
            channel.message_post(
                body="from customer", message_type="comment",
                author_id=partner.id, subtype_xmlid="mail.mt_comment")
            self.assertFalse(mock_send.called)

    def test_internal_note_not_sent(self):
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.send_message") as mock_send:
            msg = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "private note", is_internal=True)
            self.assertEqual(msg.state, "sent")
            self.assertFalse(self.env["omnichannel.job"].search(
                [("method", "=", "send_outbound")]))
            self.assertFalse(mock_send.called)
