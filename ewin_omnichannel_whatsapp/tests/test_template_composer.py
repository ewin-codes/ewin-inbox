import datetime
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTemplateComposer(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_whatsapp.channel_whatsapp")
        self.account = self.env["omnichannel.account"].create({
            "name": "WA", "channel_id": self.channel.id,
            "wa_phone_number_id": "PN1", "wa_access_token": "T",
            "wa_waba_id": "WABA1"})
        self.identity = self.env["omnichannel.identity"].create({
            "account_id": self.account.id, "external_id": "15551230000"})
        self.conversation = self.env["omnichannel.conversation"].create({
            "account_id": self.account.id, "identity_id": self.identity.id})
        self.template = self.env["omnichannel.whatsapp.template"].create({
            "account_id": self.account.id, "name": "hello",
            "language": "en_US", "status": "APPROVED", "variables_count": 2,
            "body_preview": "Hi {{1}}, order {{2}}.",
            "components": [{"type": "BODY", "text": "Hi {{1}}, order {{2}}."}]})

    def test_onchange_builds_lines(self):
        wizard = self.env["omnichannel.whatsapp.send_template.wizard"].create({
            "conversation_id": self.conversation.id,
            "template_id": self.template.id})
        wizard._onchange_template_id()
        self.assertEqual(len(wizard.line_ids), 2)
        self.assertEqual(
            sorted(wizard.line_ids.mapped("name")), ["{{1}}", "{{2}}"])

    def test_preview_renders(self):
        wizard = self.env["omnichannel.whatsapp.send_template.wizard"].create({
            "conversation_id": self.conversation.id,
            "template_id": self.template.id})
        wizard._onchange_template_id()
        lines = wizard.line_ids.sorted("sequence")
        lines[0].value = "Ann"
        lines[1].value = "A-100"
        self.assertEqual(wizard.preview, "Hi Ann, order A-100.")

    def test_action_send_calls_connector(self):
        wizard = self.env["omnichannel.whatsapp.send_template.wizard"].create({
            "conversation_id": self.conversation.id,
            "template_id": self.template.id})
        wizard._onchange_template_id()
        lines = wizard.line_ids.sorted("sequence")
        lines[0].value = "Ann"
        lines[1].value = "A-100"
        with patch("odoo.addons.ewin_omnichannel_whatsapp.services."
                   "whatsapp_api_client.WhatsAppApiClient.send_template",
                   return_value={"messages": [{"id": "wamid.T"}]}) as mocked:
            wizard.action_send()
        self.assertTrue(mocked.called)
        args = mocked.call_args.args
        # to, template_name, language, components -- components carry the
        # ordered variable values as body parameters.
        components = args[3]
        body = [c for c in components if c["type"] == "body"][0]
        self.assertEqual(
            [p["text"] for p in body["parameters"]], ["Ann", "A-100"])
        message = self.env["omnichannel.message"].search([
            ("conversation_id", "=", self.conversation.id),
            ("direction", "=", "outbound")])
        self.assertEqual(len(message), 1)
        self.assertEqual(message.body_text(), "Hi Ann, order A-100.")
        self.assertEqual(message.state, "sent")

    def test_wa_window_closed(self):
        self.conversation.last_customer_message_at = fields.Datetime.now()
        self.assertFalse(self.conversation.wa_window_closed)

        self.conversation.last_customer_message_at = (
            fields.Datetime.now() - datetime.timedelta(hours=25))
        self.assertTrue(self.conversation.wa_window_closed)

        other_channel = self.env["omnichannel.channel"].create({
            "name": "Other", "code": "other_test_channel"})
        other_account = self.env["omnichannel.account"].create({
            "name": "Other", "channel_id": other_channel.id})
        other_identity = self.env["omnichannel.identity"].create({
            "account_id": other_account.id, "external_id": "other-1"})
        other_conv = self.env["omnichannel.conversation"].create({
            "account_id": other_account.id,
            "identity_id": other_identity.id,
            "last_customer_message_at": (
                fields.Datetime.now() - datetime.timedelta(hours=48))})
        self.assertFalse(other_conv.wa_window_closed)
