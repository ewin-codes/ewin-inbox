from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

_SEND = ("odoo.addons.ewin_omnichannel_instagram.services."
         "instagram_api_client.InstagramApiClient.send_text")


@tagged("post_install", "-at_install")
class TestOutbound(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref(
            "ewin_omnichannel_instagram.channel_instagram")
        self.account = self.env["omnichannel.account"].create({
            "name": "IG", "channel_id": self.channel.id, "ig_user_id": "IG1",
            "ig_access_token": "T"})
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
        connector = self.env["omnichannel.connector.instagram"]
        msg = self._msg("hello there")
        with patch(_SEND, return_value={"message_id": "m_OUT",
                                        "recipient_id": "USER1"}) as send:
            connector.send_message(self.account, msg)
        self.assertEqual(msg.state, "sent")
        self.assertEqual(msg.external_message_id, "m_OUT")
        self.assertTrue(msg.sent_at)
        # no Human Agent tag by default (window handling opt-in)
        self.assertIsNone(send.call_args.kwargs.get("tag"))

    def test_human_agent_tag_used_when_window_closed(self):
        self.account.ig_human_agent = True  # conversation has no customer msg
        self.assertTrue(self.conversation.ig_window_closed)
        connector = self.env["omnichannel.connector.instagram"]
        msg = self._msg("late reply")
        with patch(_SEND, return_value={"message_id": "m_HA"}) as send:
            connector.send_message(self.account, msg)
        self.assertEqual(send.call_args.kwargs.get("tag"), "HUMAN_AGENT")

    def test_window_error_raises_non_retriable(self):
        from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
            import NonRetriableError
        from odoo.addons.ewin_omnichannel_instagram.services \
            .instagram_api_client import InstagramApiError
        connector = self.env["omnichannel.connector.instagram"]
        msg = self._msg("late reply")
        err = InstagramApiError(10, 2018278, "Outside window", retriable=False)
        with patch(_SEND, side_effect=err):
            with self.assertRaises(NonRetriableError):
                connector.send_message(self.account, msg)

    def test_a_friendly_error_reaches_the_log_already_translated(self):
        """The friendly texts are module-level _lt terms. Passed on lazy,
        they are resolved deep inside the ORM, where no environment is in
        reach: the operator gets the English source and the server log a
        "no translation language detected" warning for every failed send."""
        from odoo.addons.ewin_omnichannel_instagram.services \
            .instagram_api_client import InstagramApiError
        connector = self.env["omnichannel.connector.instagram"]
        with self.assertNoLogs("odoo.tools.translate", "WARNING"):
            summary = connector.handle_provider_error(
                self.account,
                InstagramApiError(
                    10, 2018278, "Outside window", retriable=False))
        self.assertIsInstance(summary, str)
