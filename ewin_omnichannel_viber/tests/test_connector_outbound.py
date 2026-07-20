from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

SEND_PATH = ("odoo.addons.ewin_omnichannel_viber.services."
             "viber_api_client.ViberApiClient.send_message")


@tagged("post_install", "-at_install")
class TestViberConnectorOutbound(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_viber.channel_viber")
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": cls.channel.id,
            "viber_auth_token": "T", "viber_bot_name": "Support"})
        cls.identity = cls.env["omnichannel.identity"].create(
            {"account_id": cls.account.id, "external_id": "user-1"})
        cls.conv = cls.env["omnichannel.conversation"].create({
            "name": "c", "account_id": cls.account.id,
            "identity_id": cls.identity.id})

    def test_outbound_text_sends_immediately(self):
        with patch(SEND_PATH, return_value={"status": 0, "message_token": 77}) \
                as mock_send:
            msg = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "Hello customer")
            self.assertTrue(mock_send.called)
            # receiver + sender name are set from the identity / account
            sent_payload = mock_send.call_args[0][0]
            self.assertEqual(sent_payload["receiver"], "user-1")
            self.assertEqual(sent_payload["sender"]["name"], "Support")
            self.assertEqual(sent_payload["type"], "text")
        self.assertEqual(msg.state, "sent")
        self.assertEqual(msg.external_message_id, "77")

    def test_outbound_image_sends_as_picture_with_public_url(self):
        att = self.env["ir.attachment"].create({
            "name": "pic.png", "mimetype": "image/png", "datas": b"aGk="})
        self.conv.write({"composer_attachment_ids": [(6, 0, att.ids)]})
        with patch(SEND_PATH, return_value={"status": 0, "message_token": 8}) \
                as mock_send:
            self.env["omnichannel.message.service"].create_outbound(
                self.conv, "", attachments=att)
        types = [c.args[0]["type"] for c in mock_send.call_args_list]
        self.assertIn("picture", types)
        pic = [c.args[0] for c in mock_send.call_args_list
               if c.args[0]["type"] == "picture"][0]
        self.assertIn("access_token=", pic["media"])
        self.assertIn(f"/web/content/{att.id}", pic["media"])

    def test_outbound_non_retriable_error_marks_failed(self):
        from odoo.addons.ewin_omnichannel_viber.services.viber_api_client \
            import ViberApiError
        with patch(SEND_PATH, side_effect=ViberApiError(
                6, "receiverNotSubscribed", retriable=False)):
            msg = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "reply")
        self.assertEqual(msg.state, "failed")

    def test_outbound_retriable_error_falls_back_to_queue(self):
        from odoo.addons.ewin_omnichannel_viber.services.viber_api_client \
            import ViberApiError
        with patch(SEND_PATH, side_effect=ViberApiError(
                12, "tooManyRequests", retriable=True)):
            msg = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "reply")
        self.assertEqual(msg.state, "queued")
        self.assertTrue(self.env["omnichannel.job"].search(
            [("method", "=", "send_outbound")]))
