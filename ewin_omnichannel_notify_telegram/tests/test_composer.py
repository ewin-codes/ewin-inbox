from unittest.mock import patch

from odoo.tests import tagged

from .common import NotifyCase


@tagged("post_install", "-at_install")
class TestComposer(NotifyCase):

    def setUp(self):
        super().setUp()
        self.service = self.env["omnichannel.telegram.notification.service"]
        self.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://example.test")

    def _lines(self, message=None):
        return self.service._compose(message or self._inbound()).split("\n")

    def _with_address(self, address):
        """Stand in for a connector that knows the account's address."""
        return patch.object(
            type(self.env["omnichannel.account"]), "_get_public_address",
            return_value=address)

    def _only_company(self):
        """Leave the conversation's company the only active one."""
        self.env["res.company"].search(
            [("id", "!=", self.company.id)]).action_archive()

    def _second_company(self, name="greedy.art"):
        """Move the conversation to a second company. The environment's own
        company stays the first, so the two cannot be confused."""
        company = self.env["res.company"].create({"name": name})
        self.account.company_id = company
        return company

    def test_text_names_channel_sender_body_and_link(self):
        self._only_company()
        headline, sender, body, link = self._lines(
            self._inbound(body="<p>Where is my order?</p>"))
        self.assertEqual(headline, "<b>Notify Test Channel</b> — Test Account")
        self.assertEqual(sender, "Ann Brown (@ann)")
        self.assertEqual(body, "Where is my order?")
        self.assertIn(f"res_id={self.conversation.id}", link)
        self.assertIn("https://example.test/mail/view", link)

    def test_one_company_is_not_named(self):
        self._only_company()
        with self._with_address("info@greedy.art"):
            headline = self._lines()[0]
        self.assertEqual(headline, "<b>Notify Test Channel</b> — info@greedy.art")

    def test_several_companies_name_the_conversations_company(self):
        self._second_company()
        with self._with_address("info@greedy.art"):
            headline = self._lines()[0]
        self.assertEqual(
            headline, "<b>greedy.art · Notify Test Channel</b> — info@greedy.art")
        self.assertNotIn(self.env.company.name, headline)

    def test_an_archived_company_is_not_counted(self):
        self._only_company()
        self.env["res.company"].create({"name": "Closed Co"}).action_archive()
        self.assertTrue(self._lines()[0].startswith("<b>Notify Test Channel</b>"))

    def test_the_public_address_follows_the_channel(self):
        with self._with_address("@shop_support_bot"):
            self.assertTrue(self._lines()[0].endswith("</b> — @shop_support_bot"))

    def test_without_an_address_the_account_name_stands_in(self):
        with self._with_address(""):
            self.assertTrue(self._lines()[0].endswith("</b> — Test Account"))

    def test_an_account_named_after_its_channel_is_not_repeated(self):
        self._only_company()
        self.account.name = "Notify Test Channel"
        with self._with_address(""):
            self.assertEqual(self._lines()[0], "<b>Notify Test Channel</b>")

    def test_company_and_address_are_escaped(self):
        self._second_company(name="Smith & <Sons>")
        with self._with_address("<shop>&co"):
            headline = self._lines()[0]
        self.assertEqual(
            headline, "<b>Smith &amp; &lt;Sons&gt; · Notify Test Channel</b>"
                      " — &lt;shop&gt;&amp;co")

    def test_the_sender_stands_on_the_second_line(self):
        self.assertEqual(self._lines()[1], "Ann Brown (@ann)")

    def test_a_sender_named_by_their_handle_is_not_repeated(self):
        self.identity.write({
            "username": False, "email": "ann@example.com",
            "display_name": "ann@example.com"})
        self.assertEqual(self._lines()[1], "ann@example.com")

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
