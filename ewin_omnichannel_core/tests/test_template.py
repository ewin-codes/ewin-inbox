from odoo.tests import tagged

from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestTemplate(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "123"})
        self.partner = self.env["res.partner"].create({"name": "Ivan"})
        self.conv = self.env["omnichannel.conversation"].create({
            "name": "Conv", "account_id": self.account.id,
            "identity_id": self.identity.id, "partner_id": self.partner.id})

    def test_render_fills_customer_name(self):
        tpl = self.env["omnichannel.template"].create(
            {"name": "Greet", "body": "Hello {{name}}, how can I help?"})
        rendered = self.env["omnichannel.template"].render_for_conversation(
            tpl.id, self.conv.id)
        self.assertEqual(rendered, "Hello Ivan, how can I help?")

    def test_render_without_placeholder(self):
        tpl = self.env["omnichannel.template"].create(
            {"name": "Bye", "body": "Goodbye!"})
        rendered = self.env["omnichannel.template"].render_for_conversation(
            tpl.id, self.conv.id)
        self.assertEqual(rendered, "Goodbye!")

    def test_render_missing_template_is_empty(self):
        rendered = self.env["omnichannel.template"].render_for_conversation(
            999999, self.conv.id)
        self.assertEqual(rendered, "")
