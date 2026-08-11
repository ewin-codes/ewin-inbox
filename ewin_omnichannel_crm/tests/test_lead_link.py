from odoo.tests import tagged

from .common import OmnichannelCrmCase


@tagged("post_install", "-at_install")
class TestLeadLink(OmnichannelCrmCase):
    def test_lead_id_is_a_history_link_field(self):
        self.assertIn(
            "lead_id",
            self.env["omnichannel.conversation"]._history_link_fields())

    def test_a_linked_lead_is_a_history_target(self):
        conv = self._new_conv(lead_id=self.lead.id)
        self.assertEqual(conv._history_targets(), [self.lead])

    def test_a_contact_and_a_lead_are_both_history_targets(self):
        conv = self._new_conv(
            partner_id=self.partner.id, lead_id=self.lead.id)
        self.assertEqual(
            conv._history_targets(), [self.partner, self.lead])

    def test_a_message_reaches_both_the_contact_and_the_lead(self):
        conv = self._new_conv(
            partner_id=self.partner.id, lead_id=self.lead.id)
        self.history.mirror(self._new_message(conv, body="Need 500 units"))
        self.assertIn("Need 500 units", self._notes(self.partner).body)
        self.assertIn("Need 500 units", self._notes(self.lead).body)

    def test_linking_a_lead_backfills_it_without_touching_the_contact(self):
        """The contact was linked first and already holds the history; adding a
        lead must fill the lead and leave the contact's copies alone."""
        conv = self._new_conv(partner_id=self.partner.id)
        self.history.mirror(self._new_message(conv, body="Need 500 units"))
        conv.lead_id = self.lead
        self.assertEqual(len(self._notes(self.partner)), 1)
        self.assertIn("Need 500 units", self._notes(self.lead).body)

    def test_unlinking_the_lead_leaves_the_contact_history_intact(self):
        conv = self._new_conv(
            partner_id=self.partner.id, lead_id=self.lead.id)
        self.history.mirror(self._new_message(conv, body="Need 500 units"))
        conv.lead_id = False
        self.assertFalse(self._notes(self.lead))
        self.assertIn("Need 500 units", self._notes(self.partner).body)

    def test_one_lead_carries_the_history_of_several_conversations(self):
        """The point of the feature: a customer who writes on two channels is
        one lead, and its chatter holds both exchanges."""
        first = self._new_conv(lead_id=self.lead.id)
        second = self._new_conv(name="Second", lead_id=self.lead.id)
        self.history.mirror(self._new_message(first, body="From Telegram"))
        self.history.mirror(self._new_message(second, body="From WhatsApp"))
        bodies = " ".join(self._notes(self.lead).mapped("body"))
        self.assertIn("From Telegram", bodies)
        self.assertIn("From WhatsApp", bodies)

    def test_deleting_the_lead_keeps_the_conversation(self):
        """A lead is a working record a salesperson may delete; the customer's
        conversation is not theirs to take with it."""
        conv = self._new_conv(lead_id=self.lead.id)
        self.lead.unlink()
        self.assertTrue(conv.exists())
        self.assertFalse(conv.lead_id)

    def test_one_lead_collects_several_conversations(self):
        """Many conversations per lead is the feature; the one2many is what
        the smart button, the count and the backfill all read."""
        first = self._new_conv(lead_id=self.lead.id)
        second = self._new_conv(name="Second", lead_id=self.lead.id)
        self.assertEqual(self.lead.omni_conversation_ids, first | second)

    def test_the_lead_counts_its_conversations(self):
        self._new_conv(lead_id=self.lead.id)
        self._new_conv(name="Second", lead_id=self.lead.id)
        self.lead.invalidate_recordset()
        self.assertEqual(self.lead.omni_conversation_count, 2)

    def test_a_lead_without_conversations_counts_zero(self):
        self.assertEqual(self.lead.omni_conversation_count, 0)

    def test_the_lead_button_opens_only_its_own_conversations(self):
        conv = self._new_conv(lead_id=self.lead.id)
        self._new_conv(name="Unrelated")
        action = self.lead.action_omni_conversations()
        found = self.env["omnichannel.conversation"].search(action["domain"])
        self.assertEqual(found, conv)

    def test_conversations_can_be_filtered_down_to_the_leadless(self):
        """`arch` holds a view's own definition; the bridge's filter only
        exists in the arch combined with its inheriting views, which is also
        what proves the inheritance resolved at all."""
        arch = self.env.ref(
            "ewin_omnichannel_core.view_conversation_search").get_combined_arch()
        self.assertIn("no_lead", arch)
