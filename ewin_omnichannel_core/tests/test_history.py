from unittest.mock import patch

from odoo.tests import tagged

from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestHistory(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "123",
             "display_name": "Ada Lovelace"})
        # mail_create_nolog: a bare create() logs its own "Contact created"
        # mail.mt_note, which would otherwise be indistinguishable from a
        # mirrored copy to _notes() below.
        self.partner = self.env["res.partner"].with_context(
            mail_create_nolog=True).create({"name": "Ada Lovelace"})
        self.note_subtype = self.env.ref("mail.mt_note")
        self.history = self.env["omnichannel.history.service"]

    def _new_conv(self, **vals):
        return self.env["omnichannel.conversation"].create(dict({
            "name": "Conv", "account_id": self.account.id,
            "identity_id": self.identity.id}, **vals))

    def _new_message(self, conv, body="Hello", **vals):
        return self.env["omnichannel.message"].create(dict({
            "conversation_id": conv.id, "direction": "inbound",
            "sender_type": "customer", "body": body}, **vals))

    def _notes(self, record):
        return record.message_ids.filtered(
            lambda m: m.subtype_id == self.note_subtype)

    def test_an_unlinked_conversation_has_no_history_targets(self):
        self.assertEqual(self._new_conv()._history_targets(), [])

    def test_history_targets_lists_the_linked_contact(self):
        conv = self._new_conv(partner_id=self.partner.id)
        self.assertEqual(conv._history_targets(), [self.partner])

    def test_partner_id_is_a_history_link_field(self):
        """The write hook keys off this list; a contact missing from it would
        silently stop backfilling and purging."""
        self.assertIn(
            "partner_id",
            self.env["omnichannel.conversation"]._history_link_fields())

    def test_mirror_copies_the_message_into_the_contact_chatter(self):
        conv = self._new_conv(partner_id=self.partner.id)
        message = self._new_message(conv, body="<p>Where is my order?</p>")
        self.history.mirror(message)
        notes = self._notes(self.partner)
        self.assertEqual(len(notes), 1)
        self.assertIn("Where is my order?", notes.body)
        self.assertEqual(message.history_message_ids, notes)

    def test_mirror_does_nothing_without_a_linked_record(self):
        message = self._new_message(self._new_conv())
        self.history.mirror(message)
        self.assertFalse(message.history_message_ids)

    def test_mirroring_twice_does_not_duplicate_the_copy(self):
        """Every message passes through mirror exactly once today, but a
        backfill racing a live message must not double-post."""
        conv = self._new_conv(partner_id=self.partner.id)
        message = self._new_message(conv)
        self.history.mirror(message)
        self.history.mirror(message)
        self.assertEqual(len(self._notes(self.partner)), 1)

    def test_the_copy_keeps_the_message_author(self):
        """The chatter renders the author avatar and name from the copy's own
        author_id — losing it would attribute the customer's words to whoever
        happened to trigger the mirror."""
        conv = self._new_conv(partner_id=self.partner.id)
        message = self._new_message(conv, author_partner_id=self.partner.id)
        self.history.mirror(message)
        self.assertEqual(self._notes(self.partner).author_id, self.partner)

    def test_the_copy_is_an_internal_note(self):
        """mail.mt_note is an internal subtype: it reaches no follower's inbox
        and is invisible to a portal user reading their own contact record."""
        conv = self._new_conv(partner_id=self.partner.id)
        self.history.mirror(self._new_message(conv))
        self.assertEqual(self._notes(self.partner).subtype_id,
                         self.note_subtype)

    def test_an_internal_note_is_mirrored_with_its_lock_marker(self):
        conv = self._new_conv(partner_id=self.partner.id)
        message = self._new_message(
            conv, body="Called the warehouse", direction="outbound",
            sender_type="operator", is_internal=True)
        self.history.mirror(message)
        self.assertIn("o_omni_internal_marker", self._notes(self.partner).body)

    def test_the_copy_carries_the_channel_badge(self):
        conv = self._new_conv(partner_id=self.partner.id)
        self.history.mirror(self._new_message(conv))
        self.assertIn("o_omni_history_entry", self._notes(self.partner).body)

    def test_the_copy_reuses_the_same_attachments(self):
        """Re-linking the ir.attachment rather than copying them keeps one
        binary per file however many records the history reaches."""
        attachment = self.env["ir.attachment"].create(
            {"name": "invoice.pdf", "datas": b"JVBERi0="})
        conv = self._new_conv(partner_id=self.partner.id)
        message = self._new_message(
            conv, attachment_ids=[(6, 0, attachment.ids)])
        self.history.mirror(message)
        self.assertEqual(self._notes(self.partner).attachment_ids, attachment)

    def _event(self, uid="123", text="Hello", message_id="987"):
        return {
            "event_id": f"test:update:{message_id}",
            "external_message_id": message_id,
            "external_user": {"id": uid, "name": "Ada Lovelace"},
            "conversation": {"external_id": uid, "type": "private"},
            "message": {"type": "text", "text": text, "attachments": [],
                        "reply_to_external_message_id": None},
            "raw_payload": {},
        }

    def test_an_inbound_message_reaches_the_contact_chatter(self):
        """The full inbound path, not the service in isolation: routing
        auto-creates the contact and links it, so the copy must appear without
        anyone touching the conversation."""
        message = self.env["omnichannel.routing.service"].process_event(
            self.account, self._event(text="My parcel is late"))
        partner = message.conversation_id.partner_id
        self.assertTrue(partner)
        self.assertIn("My parcel is late", self._notes(partner).body)

    def test_an_outbound_reply_reaches_the_contact_chatter(self):
        conv = self._new_conv(partner_id=self.partner.id)
        with patch("odoo.addons.ewin_omnichannel_core.services."
                   "routing_service.RoutingService.deliver_outbound"):
            self.env["omnichannel.message.service"].create_outbound(
                conv, "It ships tomorrow")
        self.assertIn("It ships tomorrow", self._notes(self.partner).body)

    def test_an_internal_note_reaches_the_contact_chatter(self):
        """A note about a customer belongs on the customer's card; it is never
        sent to them, so nothing leaks outward by mirroring it."""
        conv = self._new_conv(partner_id=self.partner.id)
        self.env["omnichannel.message.service"].create_outbound(
            conv, "Warehouse says Friday", is_internal=True)
        notes = self._notes(self.partner)
        self.assertIn("Warehouse says Friday", notes.body)
        self.assertIn("o_omni_internal_marker", notes.body)

    def test_a_reply_typed_in_discuss_reaches_the_contact_chatter(self):
        """The operator can answer from the mirrored Discuss channel instead of
        the Inbox form; that path builds the omni message itself and would
        otherwise skip the history."""
        conv = self._new_conv(partner_id=self.partner.id)
        channel = conv._ensure_discuss_channel()
        mail_message = channel.with_context(omni_mirror=True).message_post(
            body="Answered from Discuss", message_type="comment",
            subtype_xmlid="mail.mt_comment")
        with patch("odoo.addons.ewin_omnichannel_core.services."
                   "routing_service.RoutingService.deliver_outbound"):
            self.env["omnichannel.message.service"].\
                create_outbound_from_discuss(conv, mail_message)
        self.assertIn("Answered from Discuss", self._notes(self.partner).body)
