from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestScheduledEdit(OmnichannelCase):
    """Editing a waiting reply through the composer it was written in.

    The scheduled pane hands a reply back to the composer instead of offering
    an editor of its own. These tests own the server half of that round trip:
    what the composer is loaded with, what is written back, and what happens
    when the reply leaves while it is being edited.
    """

    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create({
            "name": "Test Account", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create({
            "account_id": self.account.id, "external_id": "cust-1"})
        self.conv = self.env["omnichannel.conversation"].create({
            "name": "Edit test", "account_id": self.account.id,
            "identity_id": self.identity.id})

    def _later(self, hours=1):
        return fields.Datetime.now() + timedelta(hours=hours)

    def _scheduled(self, body="<p>first draft</p>", when=None):
        return self.env["omnichannel.message"].create({
            "conversation_id": self.conv.id,
            "direction": "outbound",
            "sender_type": "operator",
            "message_type": "text",
            "body": body,
            "state": "scheduled",
            "scheduled_at": when or self._later(),
            "scheduled_by": self.env.uid,
        })

    def _waiting(self):
        return self.conv.omni_message_ids.filtered(
            lambda m: m.state == "scheduled")

    # -- loading the reply into the composer ---------------------------------

    def test_edit_loads_the_reply_into_the_composer(self):
        when = self._later(3)
        message = self._scheduled(body="<p>first draft</p>", when=when)
        self.conv.action_edit_scheduled(message.id)
        self.assertEqual(self.conv.composer_body, "first draft")
        self.assertEqual(self.conv.composer_scheduled_at, when)
        self.assertEqual(self.conv.composer_editing_message_id, message)

    def test_editing_leaves_internal_note_mode(self):
        """A scheduled reply is never an internal note — the service refuses
        the combination — so the composer must not stay in note mode while one
        is loaded into it."""
        self.conv.composer_is_internal = True
        message = self._scheduled()
        self.conv.action_edit_scheduled(message.id)
        self.assertFalse(self.conv.composer_is_internal)

    def test_edit_refuses_a_reply_of_another_conversation(self):
        other = self.env["omnichannel.conversation"].create({
            "name": "Someone else", "account_id": self.account.id,
            "identity_id": self.identity.id})
        message = self._scheduled()
        with self.assertRaises(UserError):
            other.action_edit_scheduled(message.id)

    def test_edit_refuses_a_reply_that_already_left(self):
        message = self._scheduled()
        message.write({"state": "sent"})
        with self.assertRaises(UserError):
            self.conv.action_edit_scheduled(message.id)

    def test_cancel_edit_clears_the_composer(self):
        message = self._scheduled()
        self.conv.action_edit_scheduled(message.id)
        self.conv.action_cancel_edit()
        self.assertFalse(self.conv.composer_editing_message_id)
        self.assertFalse(self.conv.composer_body)
        self.assertFalse(self.conv.composer_scheduled_at)
        # the reply itself is untouched: leaving the editor is not cancelling
        self.assertEqual(message.state, "scheduled")

    def test_cancelling_a_reply_being_edited_closes_the_editor(self):
        """A reply can be cancelled from the pane while it sits in the
        composer. The editor has to let go of it — a banner announcing an edit
        of something that no longer exists is worse than no banner."""
        message = self._scheduled()
        self.conv.action_edit_scheduled(message.id)
        message.action_cancel_schedule()
        self.assertFalse(self.conv.composer_editing_message_id)
        # The operator's own words are not taken away with the reply: they are
        # still there to be scheduled again.
        self.assertEqual(self.conv.composer_body, "first draft")

    def test_releasing_a_reply_being_edited_closes_the_editor(self):
        """Same for the other way out of `scheduled`: the cron's release."""
        message = self._scheduled()
        self.conv.action_edit_scheduled(message.id)
        with self._with_connector(self._fake_connector()):
            self.env["omnichannel.message.service"].release_scheduled(message)
        self.assertFalse(self.conv.composer_editing_message_id)

    def test_clearing_the_send_time_leaves_the_reply_alone(self):
        """The cross beside the picker takes the moment back and nothing else:
        the button returns to Send with the text still in the composer."""
        self.conv.write({"composer_body": "half a thought",
                         "composer_scheduled_at": self._later()})
        self.conv.action_clear_schedule_time()
        self.assertFalse(self.conv.composer_scheduled_at)
        self.assertEqual(self.conv.composer_body, "half a thought")

    # -- writing the composer back onto the reply ----------------------------

    def test_reschedule_updates_the_same_row(self):
        message = self._scheduled()
        self.conv.action_edit_scheduled(message.id)
        new_time = self._later(6)
        self.conv.write({"composer_body": "second draft",
                         "composer_scheduled_at": new_time})
        self.conv.action_schedule_reply()
        self.assertEqual(self._waiting(), message)
        self.assertEqual(message.body_text(), "second draft")
        self.assertEqual(message.scheduled_at, new_time)
        self.assertFalse(self.conv.composer_editing_message_id)
        self.assertFalse(self.conv.composer_body)

    def test_send_while_editing_delivers_the_same_row(self):
        """Send during an edit means "this wording, right now" — it must not
        leave the reply it was editing waiting behind it."""
        message = self._scheduled()
        self.conv.action_edit_scheduled(message.id)
        self.conv.composer_body = "final wording"
        with self._with_connector(self._fake_connector()):
            self.conv.action_send_reply()
        self.assertEqual(message.state, "sent")
        self.assertEqual(message.body_text(), "final wording")
        self.assertEqual(self.conv.omni_message_ids, message)

    def test_new_attachments_are_appended_and_the_old_ones_kept(self):
        old = self.env["ir.attachment"].create(
            {"name": "already-there.txt", "raw": b"old"})
        message = self._scheduled()
        message.attachment_ids = [(4, old.id)]
        self.conv.action_edit_scheduled(message.id)
        added = self.env["ir.attachment"].create(
            {"name": "just-added.txt", "raw": b"new"})
        self.conv.composer_attachment_ids = [(6, 0, added.ids)]
        self.conv.action_schedule_reply()
        self.assertEqual(message.attachment_ids, old | added)

    def _released_behind_our_back(self, message):
        """Mark the reply sent the way the cron's own conditional UPDATE does.

        An ORM write would be refused by the model itself and would prove
        nothing about the race; this leaves the row in the state a concurrent
        release leaves it in, with a stale ORM cache on top.
        """
        self.env.cr.execute(
            "UPDATE omnichannel_message SET state = 'sent' WHERE id = %s",
            (message.id,))
        message.invalidate_recordset(["state"])

    def test_reschedule_refuses_when_the_reply_left_while_being_edited(self):
        """The cron can release a reply between the click that loaded it and
        the click that saves it. The edit must be refused rather than written
        over a message the customer has already received.
        """
        message = self._scheduled()
        self.conv.action_edit_scheduled(message.id)
        self._released_behind_our_back(message)
        self.conv.composer_body = "too late"
        with self.assertRaises(UserError):
            self.conv.action_schedule_reply()
        self.assertEqual(message.body_text(), "first draft")

    def test_send_refuses_when_the_reply_left_while_being_edited(self):
        """The same race on the Send button, which is the one that needs its
        own guard: Send writes the new wording without touching the send time,
        so the model's reschedule check never runs and would let the edit land
        on a message the customer has already read.
        """
        message = self._scheduled()
        self.conv.action_edit_scheduled(message.id)
        self._released_behind_our_back(message)
        self.conv.composer_body = "too late"
        with self.assertRaises(UserError):
            self.conv.action_send_reply()
        self.assertEqual(message.body_text(), "first draft")

    # -- what the pane reads --------------------------------------------------

    def test_scheduled_replies_lists_only_what_is_still_waiting(self):
        first = self._scheduled(body="<p>later</p>", when=self._later(2))
        second = self._scheduled(body="<p>even later</p>", when=self._later(4))
        gone = self._scheduled(body="<p>gone</p>")
        gone.write({"state": "cancelled"})
        rows = self.conv.scheduled_replies()
        self.assertEqual([row["id"] for row in rows], [first.id, second.id])

    def test_scheduled_replies_carries_what_a_bubble_shows(self):
        message = self._scheduled(body="<p>see you tomorrow</p>")
        message.attachment_ids = [(0, 0, {"name": "quote.pdf", "raw": b"pdf"})]
        row = self.conv.scheduled_replies()[0]
        self.assertEqual(row["body"], "see you tomorrow")
        self.assertEqual(row["author_id"], self.env.uid)
        self.assertEqual(row["author"], self.env.user.name)
        self.assertEqual(row["attachment_count"], 1)
        self.assertTrue(row["scheduled_at"])
