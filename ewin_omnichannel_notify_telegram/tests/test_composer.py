from odoo.tests import tagged

from .common import NotifyCase


@tagged("post_install", "-at_install")
class TestComposer(NotifyCase):

    def setUp(self):
        super().setUp()
        self.service = self.env["omnichannel.telegram.notification.service"]
        self.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://example.test")

    def test_text_names_channel_sender_body_and_link(self):
        message = self._inbound(body="<p>Where is my order?</p>")
        text = self.service._compose(message)
        self.assertIn("Notify Test Channel", text)
        self.assertIn("Ann Brown", text)
        self.assertIn("Where is my order?", text)
        self.assertIn(f"res_id={self.conversation.id}", text)
        self.assertIn("https://example.test/mail/view", text)

    def test_handle_is_added_when_it_differs_from_the_name(self):
        message = self._inbound()
        self.assertIn("(@ann)", self.service._compose(message))

    def test_unnamed_customer_falls_back_to_the_handle(self):
        self.conversation.identity_id.display_name = False
        self.conversation.partner_id = False
        message = self._inbound()
        self.assertIn("@ann", self.service._compose(message))

    def test_long_body_is_cut_to_the_preview_limit(self):
        message = self._inbound(body="<p>%s</p>" % ("x" * 500))
        text = self.service._compose(message)
        self.assertIn("…", text)
        self.assertNotIn("x" * 250, text)

    def test_short_body_is_not_cut(self):
        message = self._inbound(body="<p>Short</p>")
        self.assertNotIn("…", self.service._compose(message))

    def test_body_markup_is_escaped(self):
        message = self._inbound(body="<p>&lt;b&gt;bold&lt;/b&gt; &amp; more</p>")
        text = self.service._compose(message)
        self.assertNotIn("<b>bold</b>", text)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", text)

    def test_link_ampersand_is_escaped(self):
        message = self._inbound()
        text = self.service._compose(message)
        self.assertIn("&amp;res_id=", text)
        self.assertNotIn('"&res', text)

    def test_a_message_without_text_names_its_type(self):
        message = self._inbound(body="", message_type="image")
        self.assertIn("[", self.service._compose(message))
