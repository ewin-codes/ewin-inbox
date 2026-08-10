from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestCloseReason(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "123"})
        self.reason = self.env.ref(
            "ewin_omnichannel_core.close_reason_resolved")

    def _new_conv(self):
        return self.env["omnichannel.conversation"].create({
            "name": "Conv", "account_id": self.account.id,
            "identity_id": self.identity.id})

    def test_shipped_reasons_are_not_owned_by_a_company(self):
        """The seed data leaves company_id empty on every shipped reason —
        the mechanism a second company would need to see them without
        anyone re-creating the list. (Proving that outcome itself needs a
        second-company fixture, which is out of scope here.)"""
        reasons = self.env["omnichannel.close.reason"].search([])
        self.assertGreaterEqual(len(reasons), 5)
        for xmlid in ("close_reason_resolved", "close_reason_no_answer",
                      "close_reason_spam", "close_reason_duplicate",
                      "close_reason_elsewhere"):
            reason = self.env.ref("ewin_omnichannel_core.%s" % xmlid)
            self.assertFalse(
                reason.company_id,
                "%s must be shared, not owned by one company" % xmlid)

    def test_reasons_are_ordered_by_sequence_not_by_name(self):
        """Sequence is what an administrator drags; it has to beat the
        alphabet, or reordering the list does nothing."""
        model = self.env["omnichannel.close.reason"]
        last = model.create({"name": "AAA last", "sequence": 900})
        first = model.create({"name": "ZZZ first", "sequence": 1})
        ordered = model.search([("id", "in", (first | last).ids)])
        self.assertEqual(ordered.ids, [first.id, last.id])

    def test_reason_name_unique_among_shared_reasons(self):
        """This is the regression test for the gap a plain SQL
        unique(name, company_id) constraint leaves open: Postgres treats
        two empty company_id values as distinct, so it never fires for two
        shared reasons — exactly the common case, since every shipped
        default is shared."""
        model = self.env["omnichannel.close.reason"]
        model.create({"name": "Escalated", "company_id": False})
        with self.assertRaises(ValidationError):
            model.create({"name": "Escalated", "company_id": False})

    def test_reason_name_unique_within_a_company(self):
        model = self.env["omnichannel.close.reason"]
        model.create({"name": "Escalated", "company_id": self.company.id})
        with self.assertRaises(ValidationError):
            model.create(
                {"name": "Escalated", "company_id": self.company.id})

    def test_reason_name_may_repeat_across_scopes(self):
        """The same label may exist once shared and once owned by a
        specific company: the uniqueness scope is the (name, company)
        pair, not the name alone."""
        model = self.env["omnichannel.close.reason"]
        shared = model.create({"name": "Escalated", "company_id": False})
        owned = model.create(
            {"name": "Escalated", "company_id": self.company.id})
        self.assertNotEqual(shared, owned)

    def test_archived_reason_may_share_a_name_with_an_active_one(self):
        """Archiving exists so a name can be retired and reused: the
        uniqueness invariant only covers active rows, so a duplicate of an
        archived reason must stay legal."""
        model = self.env["omnichannel.close.reason"]
        archived = model.create({"name": "Escalated", "company_id": False})
        archived.active = False
        active = model.create({"name": "Escalated", "company_id": False})
        self.assertFalse(archived.active)
        self.assertTrue(active.active)

    def test_reactivating_a_reason_re_triggers_uniqueness_check(self):
        """Regression test: archive a reason, let a new one take its name,
        then reactivate the first. The write touches only `active` — if
        that field isn't wired into the check, two active duplicates end
        up coexisting with no error."""
        model = self.env["omnichannel.close.reason"]
        archived = model.create({"name": "Escalated", "company_id": False})
        archived.active = False
        model.create({"name": "Escalated", "company_id": False})
        with self.assertRaises(ValidationError):
            archived.active = True

    def _set_policy(self, value):
        self.env["ir.config_parameter"].sudo().set_param(
            "ewin_omnichannel.close_reason_policy", value)

    def test_policy_defaults_to_off(self):
        """An existing installation must keep closing conversations the way it
        always did until an administrator turns the question on."""
        self._set_policy("")
        self.assertEqual(
            self.env["omnichannel.conversation"]._close_reason_policy(), "off")

    def test_policy_follows_the_setting(self):
        for value in ("optional", "required", "off"):
            self._set_policy(value)
            self.assertEqual(
                self.env["omnichannel.conversation"]._close_reason_policy(),
                value)

    def test_close_records_the_reason_and_the_note(self):
        conv = self._new_conv()
        conv._close(reason=self.reason, note="Refund issued")
        self.assertEqual(conv.state, "closed")
        self.assertEqual(conv.close_reason_id, self.reason)
        self.assertEqual(conv.close_note, "Refund issued")

    def test_close_posts_the_reason_to_the_chatter(self):
        """The fields hold the current closure; the chatter holds the history,
        including closures that were later reopened."""
        conv = self._new_conv()
        conv._close(reason=self.reason, note="Refund issued")
        body = conv.message_ids[0].body
        self.assertIn(self.reason.name, body)
        self.assertIn("Refund issued", body)
        self.assertIn(self.env.user.name, body)

    def test_close_without_a_reason_still_posts_who_closed_it(self):
        conv = self._new_conv()
        conv._close()
        self.assertEqual(conv.state, "closed")
        self.assertFalse(conv.close_reason_id)
        self.assertFalse(conv.close_note)
        self.assertIn(self.env.user.name, conv.message_ids[0].body)

    def test_close_escapes_the_note(self):
        """The note is operator free text posted into an HTML chatter body."""
        conv = self._new_conv()
        conv._close(note="<script>x</script>")
        body = conv.message_ids[0].body
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_close_handles_several_conversations_at_once(self):
        first, second = self._new_conv(), self._new_conv()
        (first | second)._close(reason=self.reason, note="Batch")
        for conv in (first, second):
            self.assertEqual(conv.state, "closed")
            self.assertEqual(conv.close_reason_id, self.reason)

    def test_reopen_clears_the_reason_and_the_note(self):
        """The fields describe the closure that was just undone."""
        conv = self._new_conv()
        conv._close(reason=self.reason, note="Refund issued")
        conv.action_reopen()
        self.assertEqual(conv.state, "open")
        self.assertFalse(conv.close_reason_id)
        self.assertFalse(conv.close_note)

    def test_reopen_posts_the_cleared_reason_to_the_chatter(self):
        """action_reopen wipes close_reason_id, which is also its only
        reportable copy — the chatter is the sole place the reason survives
        after that, including for the auto-reopen on an inbound reply.

        Checks the *new* top message, not just that the reason name
        appears somewhere: the close message posted earlier already
        contains it, so a body-less reopen would pass a laxer assertion
        without ever posting anything."""
        conv = self._new_conv()
        conv._close(reason=self.reason, note="Refund issued")
        conv.action_reopen()
        body = conv.message_ids[0].body
        self.assertIn("Reopened", body)
        self.assertIn(self.reason.name, body)

    def test_reopen_without_a_reason_still_posts_a_notice(self):
        conv = self._new_conv()
        conv._close()
        conv.action_reopen()
        self.assertIn("Reopened", conv.message_ids[0].body)

    def _wizard(self, convs):
        return self.env["omnichannel.close.wizard"].create(
            {"conversation_ids": [(6, 0, convs.ids)]})

    def test_wizard_confirm_closes_with_the_chosen_reason(self):
        self._set_policy("optional")
        conv = self._new_conv()
        wizard = self._wizard(conv)
        wizard.reason_id = self.reason
        result = wizard.action_confirm()
        self.assertEqual(result["type"], "ir.actions.act_window_close")
        self.assertEqual(conv.state, "closed")
        self.assertEqual(conv.close_reason_id, self.reason)

    def test_wizard_confirm_may_be_empty_when_optional(self):
        self._set_policy("optional")
        conv = self._new_conv()
        self._wizard(conv).action_confirm()
        self.assertEqual(conv.state, "closed")
        self.assertFalse(conv.close_reason_id)

    def test_wizard_refuses_an_empty_answer_when_required(self):
        """The whole point of the policy: no answer, no Closed state."""
        self._set_policy("required")
        conv = self._new_conv()
        wizard = self._wizard(conv)
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertNotEqual(conv.state, "closed")
        self.assertFalse(conv.closed_at)

    def test_wizard_treats_whitespace_as_an_empty_answer(self):
        self._set_policy("required")
        conv = self._new_conv()
        wizard = self._wizard(conv)
        wizard.note = "   \n  "
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertNotEqual(conv.state, "closed")

    def test_wizard_accepts_a_note_alone_when_required(self):
        """An operator facing a case the preset list does not cover types it
        instead of being stuck."""
        self._set_policy("required")
        conv = self._new_conv()
        wizard = self._wizard(conv)
        wizard.note = "Customer called instead"
        wizard.action_confirm()
        self.assertEqual(conv.state, "closed")
        self.assertEqual(conv.close_note, "Customer called instead")
        self.assertFalse(conv.close_reason_id)

    def test_wizard_accepts_a_reason_alone_when_required(self):
        self._set_policy("required")
        conv = self._new_conv()
        wizard = self._wizard(conv)
        wizard.reason_id = self.reason
        wizard.action_confirm()
        self.assertEqual(conv.state, "closed")
        self.assertEqual(conv.close_reason_id, self.reason)

    def test_wizard_closes_every_conversation_it_was_given(self):
        self._set_policy("required")
        first, second = self._new_conv(), self._new_conv()
        wizard = self._wizard(first | second)
        wizard.reason_id = self.reason
        wizard.action_confirm()
        for conv in (first, second):
            self.assertEqual(conv.state, "closed")
            self.assertEqual(conv.close_reason_id, self.reason)

    def test_close_button_closes_directly_when_the_policy_is_off(self):
        self._set_policy("off")
        conv = self._new_conv()
        self.assertTrue(conv.action_close())
        self.assertEqual(conv.state, "closed")

    def test_close_button_opens_the_wizard_when_a_reason_is_wanted(self):
        for policy in ("optional", "required"):
            self._set_policy(policy)
            conv = self._new_conv()
            action = conv.action_close()
            self.assertEqual(action["type"], "ir.actions.act_window")
            self.assertEqual(action["res_model"], "omnichannel.close.wizard")
            self.assertEqual(action["target"], "new")
            self.assertEqual(
                action["context"]["default_conversation_ids"],
                [(6, 0, conv.ids)])
            # the button itself must not have closed anything
            self.assertNotEqual(conv.state, "closed")
            self.assertFalse(conv.closed_at)

    def test_close_button_hands_every_selected_conversation_to_the_wizard(
            self):
        self._set_policy("required")
        first, second = self._new_conv(), self._new_conv()
        action = (first | second).action_close()
        self.assertEqual(
            action["context"]["default_conversation_ids"],
            [(6, 0, (first | second).ids)])

    def test_the_reason_is_groupable_from_the_search_view(self):
        """A manager answering 'why are we closing chats' should not need
        SQL."""
        view = self.env.ref("ewin_omnichannel_core.view_conversation_search")
        self.assertIn("g_close_reason", view.arch)
        self.assertIn("close_reason_id", view.arch)

    def test_grouping_conversations_by_close_reason_works(self):
        conv = self._new_conv()
        conv._close(reason=self.reason)
        groups = self.env["omnichannel.conversation"]._read_group(
            [("id", "=", conv.id)], ["close_reason_id"], ["__count"])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0], self.reason)
