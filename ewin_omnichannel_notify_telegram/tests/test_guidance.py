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

    def test_the_form_walks_through_the_four_steps(self):
        text = " ".join(self._form(self.notifier).itertext())
        for step in ("Step 1 of 4", "Step 2 of 4", "Step 3 of 4",
                     "Step 4 of 4"):
            self.assertIn(step, text)
        self.assertIn("@BotFather", text)
        self.assertIn("/newbot", text)
        self.assertIn("/register", text)

    def test_the_form_says_where_an_operator_connects(self):
        # The one question the fields cannot answer: an operator types
        # neither a username nor a chat id, anywhere.
        text = " ".join(self._form(self.notifier).itertext())
        self.assertIn("Connect Telegram", text)
        self.assertIn("Preferences", text)

    def test_the_form_says_what_the_group_chat_is_for(self):
        # "Why do I need a group at all" is the question that follows
        # straight after "what do I type in Group Chat ID".
        text = " ".join(self._form(self.notifier).itertext())
        self.assertIn("no operator has taken yet", text)

    def test_the_personal_step_tracks_the_reader_not_the_record(self):
        """Step 3 is about whoever opened the form.

        It is the one step that is not a property of the notifier: two
        administrators looking at the same record are at different points
        in it, so the flag it hangs on is computed per user.
        """
        self.assertFalse(self.notifier.my_telegram_connected)
        self.env.user.sudo().omni_tg_chat_id = "555"
        self.notifier.invalidate_recordset()
        self.assertTrue(self.notifier.my_telegram_connected)

    def test_another_user_sees_their_own_answer(self):
        self.env.user.sudo().omni_tg_chat_id = "555"
        other = self.env["res.users"].create({
            "name": "Other", "login": "guidance_other",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_admin").id)]})
        self.assertFalse(
            self.notifier.with_user(other).my_telegram_connected,
            "depends_context('uid') keys the cache by the reader")

    def test_the_linking_link_is_a_link(self):
        """The one interactive step of the setup.

        As a CopyClipboardChar the address was a string to select and
        paste; CopyClipboardURL renders it as an anchor and keeps the copy
        button for a link being moved to another device.
        """
        arch = etree.fromstring(self.env["omnichannel.telegram.link"]
                                .get_view(view_type="form")["arch"])
        url = arch.xpath("//field[@name='url']")
        self.assertEqual(len(url), 1)
        self.assertEqual(url[0].get("widget"), "CopyClipboardURL")

    def test_connecting_is_a_button_not_a_caption(self):
        """In Preferences it read as a line of text among the fields.

        Read as an operator: the whole block is behind that group, and
        Odoo strips a node the reader's groups do not reach - so the
        default test user would see an empty arch and the assertion would
        pass or fail on who is asking rather than on what is there.
        """
        operator = self.env["res.users"].create({
            "name": "Operator", "login": "guidance_operator",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        arch = etree.fromstring(
            self.env["res.users"].with_user(operator).get_view(
                view_id=self.env.ref(
                    "base.view_users_form_simple_modif").id,
                view_type="form")["arch"])
        button = arch.xpath("//button[@name='action_omni_tg_link']")
        self.assertEqual(len(button), 1)
        self.assertIn("btn-primary", button[0].get("class"))

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
