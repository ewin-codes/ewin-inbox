from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestGuidance(TransactionCase):
    """What the forms have to say for themselves.

    The setup runs across three places - Odoo, @BotFather and a Telegram
    group - and two of the three steps happen outside this screen. A form
    that only shows fields leaves the administrator guessing which bot,
    which chat, and what an operator is supposed to do; these assertions
    pin the parts of that explanation that are easy to delete by accident.
    """

    def setUp(self):
        super().setUp()
        self.notifier = self.env["omnichannel.telegram.notifier"].create({
            "name": "Notifier", "bot_token": "T"})

    def _form(self, record):
        return etree.fromstring(record.get_view(view_type="form")["arch"])

    def test_the_group_chat_field_says_it_holds_an_id(self):
        # It is a numeric chat id, and the label read "Group Chat" because
        # Odoo strips a trailing _id when it invents one.
        self.assertEqual(
            self.notifier._fields["group_chat_id"].string, "Group Chat ID")

    def test_the_group_chat_help_says_not_to_type_it(self):
        help_text = self.notifier._fields["group_chat_id"].help
        self.assertIn("/register", help_text)
        self.assertIn("nothing to type here", help_text)

    def test_the_form_walks_through_the_three_steps(self):
        text = " ".join(self._form(self.notifier).itertext())
        for step in ("Step 1 of 3", "Step 2 of 3", "Step 3 of 3"):
            self.assertIn(step, text)
        self.assertIn("@BotFather", text)
        self.assertIn("/register", text)

    def test_the_form_says_where_an_operator_connects(self):
        # The one question the fields cannot answer: an operator types
        # neither a username nor a chat id, anywhere.
        text = " ".join(self._form(self.notifier).itertext())
        self.assertIn("Connect Telegram", text)
        self.assertIn("Preferences", text)

    def test_a_telegram_account_points_at_the_notifier(self):
        """The account form is where somebody hunting for "the Telegram
        settings" lands first, and it is the wrong screen."""
        account = self.env["omnichannel.account"]
        text = " ".join(self._form(account).itertext())
        self.assertIn("Telegram Notifications", text)

    def test_that_note_is_scoped_to_telegram_accounts(self):
        # Located by its condition rather than by its words: the sentence
        # is split across <b> elements, so an xpath on text() would match
        # only the first fragment and pass or fail on the phrasing.
        arch = self._form(self.env["omnichannel.account"])
        notes = arch.xpath("//div[@invisible=\"channel_code != 'telegram'\"]")
        self.assertEqual(
            len(notes), 1,
            "an Email or WhatsApp account must not carry a Telegram note")
        self.assertIn("Telegram Notifications", " ".join(notes[0].itertext()))
