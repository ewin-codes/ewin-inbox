from datetime import timedelta
from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestScheduledSend(OmnichannelCase):
    # The cron's row lock and per-message commits are guarded by the testing
    # flag, so these tests cannot exercise those windows. The re-check for
    # scheduled_at re-evaluation is testable in a single transaction, as it is.
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create({
            "name": "Test Account", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create({
            "account_id": self.account.id, "external_id": "cust-1"})
        self.conv = self.env["omnichannel.conversation"].create({
            "name": "Scheduled test", "account_id": self.account.id,
            "identity_id": self.identity.id})

    def _later(self, hours=1):
        return fields.Datetime.now() + timedelta(hours=hours)

    def _scheduled_message(self, when=None):
        """A scheduled row written directly, with no service involved — what is
        under test here is the model's own guard, not the way in."""
        return self.env["omnichannel.message"].create({
            "conversation_id": self.conv.id,
            "direction": "outbound",
            "sender_type": "operator",
            "message_type": "text",
            "body": "<p>later</p>",
            "state": "scheduled",
            "scheduled_at": when or self._later(),
            "scheduled_by": self.env.uid,
        })

    def _fake_connector(self):
        """Stand in for a channel connector.

        The core's test channel has no connector addon behind it, so a real
        delivery attempt would raise — patching the lookup keeps this suite
        independent of which connector modules happen to be installed.
        ``send_message`` marks the message sent, exactly as every real
        connector does.
        """
        connector = MagicMock()

        def send_message(account, message):
            message.write({
                "state": "sent",
                "external_message_id": "ext-1",
                "sent_at": fields.Datetime.now(),
            })
            return True

        connector.send_message.side_effect = send_message
        return connector

    def _with_connector(self, connector):
        """Patch account._get_connector for the duration of a `with` block."""
        return patch.object(
            type(self.env["omnichannel.account"]), "_get_connector",
            return_value=connector)

    def test_reschedule_while_waiting(self):
        message = self._scheduled_message()
        new_time = self._later(5)
        message.write({"scheduled_at": new_time})
        self.assertEqual(message.scheduled_at, new_time)

    def test_reschedule_into_the_past_refused(self):
        message = self._scheduled_message()
        with self.assertRaises(UserError):
            message.write(
                {"scheduled_at": fields.Datetime.now() - timedelta(minutes=1)})

    def test_send_time_frozen_once_it_has_left(self):
        message = self._scheduled_message()
        original_scheduled_at = message.scheduled_at
        original_scheduled_by = message.scheduled_by
        message.write({"state": "sent"})
        # Verify the scheduling metadata survives delivery
        self.assertEqual(message.scheduled_at, original_scheduled_at)
        self.assertEqual(message.scheduled_by, original_scheduled_by)
        # Verify the send time cannot be changed once sent
        with self.assertRaises(UserError):
            message.write({"scheduled_at": self._later(2)})

    def test_scheduled_state_requires_a_time(self):
        with self.assertRaises(ValidationError):
            self.env["omnichannel.message"].create({
                "conversation_id": self.conv.id,
                "direction": "outbound",
                "sender_type": "operator",
                "message_type": "text",
                "state": "scheduled",
            })

    def test_create_with_past_scheduled_at_refused(self):
        with self.assertRaises(UserError):
            self.env["omnichannel.message"].create({
                "conversation_id": self.conv.id,
                "direction": "outbound",
                "sender_type": "operator",
                "message_type": "text",
                "body": "<p>later</p>",
                "state": "scheduled",
                "scheduled_at": fields.Datetime.now() - timedelta(minutes=1),
                "scheduled_by": self.env.uid,
            })

    def test_scheduling_delivers_nothing(self):
        connector = self._fake_connector()
        with self._with_connector(connector):
            message = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "<p>see you tomorrow</p>",
                scheduled_at=self._later())
        connector.send_message.assert_not_called()
        self.assertEqual(message.state, "scheduled")
        self.assertEqual(message.scheduled_by, self.env.user)
        self.assertFalse(self.env["omnichannel.job"].search(
            [("method", "=", "send_outbound")]))

    def test_scheduling_leaves_thread_and_metrics_untouched(self):
        with self._with_connector(self._fake_connector()):
            message = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "<p>see you tomorrow</p>",
                scheduled_at=self._later())
        # not in the customer-facing thread: it keeps showing what the customer
        # has actually seen
        self.assertFalse(message.mail_message_id)
        self.assertFalse(self.conv.discuss_channel_id.message_ids)
        # and not counted as an answer: response time must span up to the real
        # delivery, not up to the moment it was planned
        self.assertFalse(self.conv.first_operator_message_at)
        self.assertFalse(self.conv.last_message_at)

    def test_scheduling_takes_the_conversation(self):
        self.assertFalse(self.conv.operator_id)
        with self._with_connector(self._fake_connector()):
            self.env["omnichannel.message.service"].create_outbound(
                self.conv, "<p>see you tomorrow</p>",
                scheduled_at=self._later())
        self.assertEqual(self.conv.operator_id, self.env.user)

    def test_internal_note_cannot_be_scheduled(self):
        with self.assertRaises(UserError):
            self.env["omnichannel.message.service"].create_outbound(
                self.conv, "<p>remind me</p>", is_internal=True,
                scheduled_at=self._later())

    def _schedule(self, when=None, body="<p>see you tomorrow</p>"):
        """Schedule a reply the way the composer does."""
        with self._with_connector(self._fake_connector()):
            return self.env["omnichannel.message.service"].create_outbound(
                self.conv, body, scheduled_at=when or self._later())

    def test_release_delivers_and_mirrors(self):
        message = self._schedule()
        connector = self._fake_connector()
        with self._with_connector(connector):
            self.env["omnichannel.message.service"].release_scheduled(message)
        connector.send_message.assert_called_once()
        self.assertEqual(message.state, "sent")
        # now it belongs in the thread and on the conversation's clock
        self.assertTrue(message.mail_message_id)
        self.assertTrue(self.conv.first_operator_message_at)
        self.assertTrue(self.conv.last_message_at)

    def test_scheduled_attachment_reaches_the_mirror_and_the_connector(self):
        """The spec puts attachments explicitly in scope: _create_scheduled
        stores them and _mirror_to_discuss passes them on, but neither is
        proof that one survives all the way to release — this is."""
        attachment = self.env["ir.attachment"].create(
            {"name": "brochure.pdf", "datas": b"JVBERi0="})
        connector = self._fake_connector()
        with self._with_connector(connector):
            message = self.env["omnichannel.message.service"].create_outbound(
                self.conv, "<p>see attached</p>",
                attachments=attachment, scheduled_at=self._later())
        self.assertEqual(message.attachment_ids, attachment)
        # still parked: nothing reaches the thread while only scheduled
        self.assertFalse(self.conv.discuss_channel_id.message_ids)
        with self._with_connector(connector):
            self.env["omnichannel.message.service"].release_scheduled(message)
        mirrored = self.conv.discuss_channel_id.message_ids
        self.assertEqual(len(mirrored), 1)
        self.assertIn(attachment, mirrored.attachment_ids)
        connector.send_message.assert_called_once()
        sent_message = connector.send_message.call_args[0][1]
        self.assertIn(attachment, sent_message.attachment_ids)

    def test_release_is_idempotent(self):
        message = self._schedule()
        connector = self._fake_connector()
        with self._with_connector(connector):
            service = self.env["omnichannel.message.service"]
            service.release_scheduled(message)
            service.release_scheduled(message)
        self.assertEqual(connector.send_message.call_count, 1)
        # exactly one post in the mirror channel: a second release would post
        # again and simply move mail_message_id, so counting the channel is
        # what actually proves it, not looking the id up.
        self.assertEqual(len(self.conv.discuss_channel_id.message_ids), 1)

    def test_release_reopens_a_closed_conversation(self):
        message = self._schedule()
        self.conv._close()
        self.assertEqual(self.conv.state, "closed")
        with self._with_connector(self._fake_connector()):
            self.env["omnichannel.message.service"].release_scheduled(message)
        self.assertEqual(self.conv.state, "open")
        self.assertEqual(message.state, "sent")

    def test_response_time_is_measured_at_delivery(self):
        self.conv.write({
            "first_customer_message_at": fields.Datetime.now() - timedelta(hours=2)})
        message = self._schedule()
        # planning alone must not stop the clock
        self.assertEqual(self.conv.first_response_seconds, 0)
        with self._with_connector(self._fake_connector()):
            self.env["omnichannel.message.service"].release_scheduled(message)
        self.assertGreaterEqual(self.conv.first_response_seconds, 7200)

    def test_release_is_guarded_at_database_level(self):
        """The database guard reads the committed row, not the ORM cache.

        A concurrent caller can pass an ORM-based check against a stale cache:
        the row locked and updated by another transaction, while the local cache
        still says the old value. The SQL WHERE clause re-evaluated after the
        lock is granted catches this, refusing to update a row that no longer
        matches the condition. This test proves the guard works at the database
        level, not the cache level, by simulating the stale-cache scenario: the
        row is moved out from under the cached state without invalidating the
        cache, then a release is called and correctly refuses to send.
        """
        message = self._schedule()
        # The Python cache now holds: state = "scheduled"
        self.assertEqual(message.state, "scheduled")
        # Move the row out from under that cache — raw SQL, do not touch ORM.
        # This simulates what another transaction does while we hold the stale
        # cache: it moves the row to sent.
        self.env.cr.execute(
            "UPDATE omnichannel_message SET state = %s WHERE id = %s",
            ("sent", message.id))
        # The Python cache still says "scheduled" — that is the whole point.
        # If the guard were cache-based, release_scheduled would proceed.
        # If the guard is database-based, it will refuse.
        connector = self._fake_connector()
        with self._with_connector(connector):
            self.env["omnichannel.message.service"].release_scheduled(message)
        # The connector was never called: the WHERE state = 'scheduled' matched
        # no row, so release_scheduled bailed out without reaching delivery.
        self.assertEqual(connector.send_message.call_count, 0)
        # No post in the mirror channel: release never ran the finalize sequence.
        self.assertEqual(len(self.conv.discuss_channel_id.message_ids), 0)

    def test_cron_releases_a_due_message(self):
        message = self._schedule(self._later(1))
        connector = self._fake_connector()
        due = fields.Datetime.now() + timedelta(hours=2)
        with patch.object(fields.Datetime, "now", return_value=due), \
             self._with_connector(connector):
            self.env["omnichannel.message"]._cron_send_scheduled()
        connector.send_message.assert_called_once()
        self.assertEqual(message.state, "sent")

    def test_cron_leaves_a_future_message_alone(self):
        message = self._schedule(self._later(5))
        connector = self._fake_connector()
        with self._with_connector(connector):
            self.env["omnichannel.message"]._cron_send_scheduled()
        connector.send_message.assert_not_called()
        self.assertEqual(message.state, "scheduled")

    def test_cron_respects_reschedule_during_drain(self):
        """The cron re-checks scheduled_at before releasing each message.

        When the cron is draining a backlog, an operator can reschedule a
        message that is already in the batch. The re-lock query re-evaluates
        both state and scheduled_at, so a message moved out of the due range
        is skipped and tried again next tick, not released today.
        """
        first = self._schedule(self._later(1))
        second = self._schedule(self._later(2))
        connector = self._fake_connector()
        original_send = connector.send_message.side_effect

        def send_with_reschedule(account, message):
            if message.id == first.id:
                # On sending the first message, reschedule the second one
                # a day into the future using raw SQL (simulating a concurrent
                # transaction that the ORM cache and write guard don't see).
                self.env.cr.execute(
                    "UPDATE omnichannel_message SET scheduled_at = %s "
                    "WHERE id = %s",
                    (fields.Datetime.now() + timedelta(days=1), second.id))
            return original_send(account, message)

        connector.send_message.side_effect = send_with_reschedule
        due = fields.Datetime.now() + timedelta(hours=3)
        with patch.object(fields.Datetime, "now", return_value=due), \
             self._with_connector(connector):
            self.env["omnichannel.message"]._cron_send_scheduled()
        # The second message was rescheduled while the cron was draining.
        # The re-check in _cron_send_scheduled should see the new scheduled_at
        # and skip the message, leaving it in scheduled state.
        self.assertEqual(first.state, "sent")
        self.assertEqual(second.state, "scheduled")

    def test_cron_failure_logs_and_keeps_the_message_scheduled(self):
        """A release that raises must not vanish silently and must not stop
        the batch. No retry counter: the message just stays scheduled for
        the next tick, and the only trace an operator can see between tries
        is this log entry — the panel row just looks like its time passed."""
        message = self._schedule(self._later(1))
        due = fields.Datetime.now() + timedelta(hours=2)
        with patch.object(fields.Datetime, "now", return_value=due), \
             patch.object(
                 type(self.env["omnichannel.message.service"]),
                 "release_scheduled", side_effect=RuntimeError("boom")):
            self.env["omnichannel.message"]._cron_send_scheduled()
        self.assertEqual(message.state, "scheduled")
        log = self.env["omnichannel.error.log"].search(
            [("message_id", "=", message.id)])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.category, "internal")
        self.assertEqual(log.conversation_id, self.conv)
        self.assertIn("boom", log.technical)

    def test_cron_record_exists(self):
        """Verify the scheduled action is registered and active."""
        cron = self.env.ref("ewin_omnichannel_core.cron_send_scheduled_messages")
        self.assertTrue(cron.active)
        self.assertEqual(cron.interval_number, 1)
        self.assertEqual(cron.interval_type, "minutes")

    def test_send_now_delivers_ahead_of_time(self):
        message = self._schedule(self._later(5))
        connector = self._fake_connector()
        with self._with_connector(connector):
            message.action_send_now()
        connector.send_message.assert_called_once()
        self.assertEqual(message.state, "sent")

    def test_cancel_keeps_the_row_and_sends_nothing(self):
        message = self._schedule()
        connector = self._fake_connector()
        with self._with_connector(connector):
            message.action_cancel_schedule()
            self.env["omnichannel.message"]._cron_send_scheduled()
        connector.send_message.assert_not_called()
        self.assertEqual(message.state, "cancelled")
        self.assertTrue(message.exists())

    def test_cancel_refused_once_it_has_left(self):
        message = self._schedule()
        with self._with_connector(self._fake_connector()):
            self.env["omnichannel.message.service"].release_scheduled(message)
        with self.assertRaises(UserError):
            message.action_cancel_schedule()

    def test_operator_cannot_read_another_operators_scheduled_message(self):
        """The Scheduled menu is company-wide and ungrouped: the record rule,
        not the menu, has to keep an operator's pending reply — body,
        conversation and author — away from a colleague who is neither the
        conversation's operator nor on its team."""
        operator_a = self.env["res.users"].create({
            "name": "Sched Op A", "login": "sched_op_a",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        operator_b = self.env["res.users"].create({
            "name": "Sched Op B", "login": "sched_op_b",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        self.conv.operator_id = operator_a
        message = self._scheduled_message()
        self.assertEqual(
            self.env["omnichannel.message"].with_user(operator_a).search(
                [("id", "=", message.id)]),
            message)
        self.assertFalse(
            self.env["omnichannel.message"].with_user(operator_b).search(
                [("id", "=", message.id)]))
        with self.assertRaises(AccessError):
            message.with_user(operator_b).body

    def test_cancel_refuses_a_caller_with_no_write_access(self):
        """action_cancel_schedule's transition is a raw UPDATE, which no
        record rule can constrain — the access check has to happen before
        it runs, not be left to something downstream noticing by accident."""
        message = self._scheduled_message()
        outsider = self.env["res.users"].create({
            "name": "No Omni Access", "login": "sched_outsider",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])]})
        with self.assertRaises(AccessError):
            message.with_user(outsider).action_cancel_schedule()
        self.env.cr.execute(
            "SELECT state FROM omnichannel_message WHERE id = %s",
            (message.id,))
        self.assertEqual(self.env.cr.fetchone()[0], "scheduled")

    def test_reschedule_guard_checks_actual_state_not_cache(self):
        """The reschedule guard reads the database row, not the ORM cache.

        A concurrent release can complete between the ORM cache read and the
        UPDATE, leaving a reschedule to silently land on a message that already
        went out. The raw SQL UPDATE here simulates exactly what another
        transaction does while we hold a stale cache: it moves the row to sent.
        This proves the guard is DB-based rather than cache-based — a plain
        SELECT with no lock would pass this same test. Preventing the race
        from landing in the first place, rather than merely detecting it here,
        is the row lock's own job.
        """
        message = self._scheduled_message()
        # The Python cache now holds: state = "scheduled"
        self.assertEqual(message.state, "scheduled")
        # Move the row out from under that cache — raw SQL, do not touch ORM.
        # This simulates what the cron does while we hold the stale cache.
        self.env.cr.execute(
            "UPDATE omnichannel_message SET state = %s WHERE id = %s",
            ("sent", message.id))
        # The Python cache still says "scheduled" — that is the whole point.
        # The reschedule guard must lock the row, see the true state, and refuse.
        with self.assertRaises(UserError):
            message.write({"scheduled_at": self._later(5)})

    def test_cancel_refuses_race_when_cron_releases_first(self):
        """The cancel guard refuses to overwrite a message the cron sent.

        A concurrent release can complete between the state check and the
        UPDATE, leaving the cancel to stamp 'cancelled' on a message that has
        already been sent. The raw SQL UPDATE here simulates exactly what the
        cron does while we hold a stale cache: it moves the row to queued
        (and the connector will move it to sent). Without an UPDATE predicate
        the cancel would go through; with one the guard sees the truth and
        raises. The chatter line must not be posted when the cancel is refused.
        """
        message = self._scheduled_message()
        # The Python cache now holds: state = "scheduled"
        self.assertEqual(message.state, "scheduled")
        # Move the row out from under that cache — raw SQL, do not touch ORM.
        # This simulates what the cron does while we hold the stale cache.
        self.env.cr.execute(
            "UPDATE omnichannel_message SET state = %s WHERE id = %s",
            ("sent", message.id))
        # The Python cache still says "scheduled" — that is the whole point.
        # The cancel guard must lock the row, see the true state, and refuse.
        with self.assertRaises(UserError):
            message.action_cancel_schedule()
        # Verify the state is still sent (not overwritten to cancelled)
        self.env.cr.execute("SELECT state FROM omnichannel_message WHERE id = %s", (message.id,))
        actual_state = self.env.cr.fetchone()[0]
        self.assertEqual(actual_state, "sent")
        # Verify no cancellation line was posted to the conversation
        cancel_posts = message.conversation_id.message_ids.filtered(
            lambda m: "cancelled" in (m.body or "").lower())
        self.assertFalse(cancel_posts)

    def test_send_now_tolerates_race_when_cron_releases_first(self):
        """The send-now action tolerates losing a race to the cron.

        Both can genuinely fire in the same second. Releasing through
        release_scheduled first (as the previous version of this test did)
        leaves the ORM cache holding state == "sent", so action_send_now's own
        cached-state check short-circuits before ever calling
        release_scheduled again — that proves only the cache guard, not the
        boolean gate ("if released:") that exists for exactly this race.
        Moving the row with raw SQL, the way the sibling database-level-guard
        tests do, keeps the cache saying "scheduled" so the call reaches
        release_scheduled, loses the race there, and the gate is what has to
        stop the audit post.
        """
        message = self._schedule(self._later(5))
        self.assertEqual(message.state, "scheduled")
        # Move the row out from under the cache — raw SQL, do not touch ORM.
        # This simulates another transaction (the cron) releasing and sending
        # it while this cache still says "scheduled".
        self.env.cr.execute(
            "UPDATE omnichannel_message SET state = %s WHERE id = %s",
            ("sent", message.id))
        connector = self._fake_connector()
        with self._with_connector(connector):
            message.action_send_now()
        # The cached state passed action_send_now's own check, so it reached
        # release_scheduled — whose UPDATE ... WHERE state = 'scheduled'
        # matched no row and returned False, never reaching delivery.
        connector.send_message.assert_not_called()
        # No audit line credits the operator for a release that lost the race.
        send_now_posts = message.conversation_id.message_ids.filtered(
            lambda m: "sent now by" in (m.body or "").lower())
        self.assertFalse(send_now_posts)

    def test_reschedule_posts_chatter_with_both_times(self):
        """A reschedule posts a chatter line naming the user and both times."""
        message = self._scheduled_message(self._later(2))
        old_time = message.scheduled_at
        new_time = self._later(5)
        # Clear any existing posts (from creation)
        self.conv.message_ids.unlink()
        # Reschedule the message
        message.write({"scheduled_at": new_time})
        # Verify exactly one reschedule post was added
        reschedule_posts = self.conv.message_ids.filtered(
            lambda m: "rescheduled" in (m.body or "").lower())
        self.assertEqual(len(reschedule_posts), 1)
        # Verify the post names both times and the user
        post_body = reschedule_posts[0].body or ""
        self.assertIn(self.env.user.name, post_body)
        # The times should be formatted and both should appear in the post
        service = self.env["omnichannel.message.service"]
        old_formatted = service._format_scheduled(old_time)
        new_formatted = service._format_scheduled(new_time)
        self.assertIn(old_formatted, post_body)
        self.assertIn(new_formatted, post_body)

    def test_action_schedule_reply_reads_the_stored_composer(self):
        self.conv.write({
            "composer_body": "operator reply",
            "composer_scheduled_at": self._later(3),
        })
        connector = self._fake_connector()
        with self._with_connector(connector):
            self.conv.action_schedule_reply()
        connector.send_message.assert_not_called()
        message = self.env["omnichannel.message"].search(
            [("conversation_id", "=", self.conv.id),
             ("state", "=", "scheduled")])
        self.assertEqual(len(message), 1)
        self.assertIn("operator reply", message.body or "")
        # composer cleared, so the next reply starts empty
        self.assertFalse(self.conv.composer_body)
        self.assertFalse(self.conv.composer_scheduled_at)

    def test_action_schedule_reply_needs_a_time(self):
        self.conv.write({"composer_body": "operator reply"})
        with self.assertRaises(UserError):
            self.conv.action_schedule_reply()

    def test_action_schedule_reply_refuses_an_internal_note(self):
        self.conv.write({
            "composer_body": "remind me",
            "composer_is_internal": True,
            "composer_scheduled_at": self._later(3),
        })
        with self.assertRaises(UserError):
            self.conv.action_schedule_reply()

    def test_panel_shows_only_waiting_replies(self):
        first = self._schedule(self._later(2))
        second = self._schedule(self._later(4))
        # Verify grouping is per-conversation: a second conversation should
        # have its own count, not share the first's.
        conv2 = self.env["omnichannel.conversation"].create({
            "name": "Second conversation", "account_id": self.account.id,
            "identity_id": self.identity.id})
        third = self.env["omnichannel.message"].create({
            "conversation_id": conv2.id,
            "direction": "outbound",
            "sender_type": "operator",
            "message_type": "text",
            "body": "<p>later</p>",
            "state": "scheduled",
            "scheduled_at": self._later(3),
            "scheduled_by": self.env.uid,
        })
        self.assertEqual(self.conv.scheduled_count, 2)
        self.assertIn("2", self.conv.scheduled_badge or "")
        self.assertEqual(conv2.scheduled_count, 1)
        self.assertIn("1", conv2.scheduled_badge or "")
        # Release one from the first conversation
        with self._with_connector(self._fake_connector()):
            self.env["omnichannel.message.service"].release_scheduled(first)
        # Both conversations should update without manual invalidation
        self.assertEqual(self.conv.scheduled_count, 1)
        self.assertIn("1", self.conv.scheduled_badge or "")
        self.assertEqual(conv2.scheduled_count, 1)
        self.assertIn("1", conv2.scheduled_badge or "")

    def test_badge_is_empty_without_scheduled_replies(self):
        self.assertFalse(self.conv.scheduled_badge)

    def test_message_volume_excludes_unsent_by_a_removable_default(self):
        """A scheduled message has not gone out and a cancelled one never
        will, so neither should inflate outbound volume — but a hard domain
        on the action would make the Scheduled/Cancelled search filters that
        already exist permanently unreachable. The correction has to be a
        removable default filter, not a domain baked into the action."""
        action = self.env.ref("ewin_omnichannel_core.action_report_messages")
        self.assertFalse(action.domain)
        self.assertIn("search_default_real_volume", action.context)
        view = self.env.ref("ewin_omnichannel_core.view_message_search")
        self.assertIn('name="real_volume"', view.arch)
