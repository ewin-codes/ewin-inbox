from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import OmnichannelCrmCase


@tagged("post_install", "-at_install")
class TestCreateLead(OmnichannelCrmCase):
    def test_create_lead_links_the_new_lead_to_the_conversation(self):
        conv = self._new_conv()
        action = conv.action_create_lead()
        self.assertTrue(conv.lead_id)
        self.assertEqual(action["res_id"], conv.lead_id.id)
        self.assertEqual(action["res_model"], "crm.lead")

    def test_create_lead_seeds_the_customer_details_from_the_identity(self):
        """The channel already knows who this is; retyping it is the step the
        button exists to remove."""
        conv = self._new_conv()
        conv.action_create_lead()
        self.assertEqual(conv.lead_id.email_from, "ada@example.com")
        self.assertEqual(conv.lead_id.phone, "+490001")
        self.assertEqual(conv.lead_id.contact_name, "Ada Lovelace")

    def test_create_lead_prefers_the_linked_contact_over_a_free_text_name(self):
        conv = self._new_conv(partner_id=self.partner.id)
        conv.action_create_lead()
        self.assertEqual(conv.lead_id.partner_id, self.partner)
        self.assertFalse(conv.lead_id.contact_name)

    def test_create_lead_names_the_lead_after_the_subject_when_there_is_one(self):
        conv = self._new_conv(subject="Quote for 500 units")
        conv.action_create_lead()
        self.assertEqual(conv.lead_id.name, "Quote for 500 units")

    def test_create_lead_names_the_lead_after_the_customer_otherwise(self):
        """Chat channels carry no subject, so the fallback is what most leads
        are actually called."""
        conv = self._new_conv()
        conv.action_create_lead()
        self.assertIn("Ada Lovelace", conv.lead_id.name)
        self.assertIn(self.channel.name, conv.lead_id.name)

    def test_create_lead_assigns_the_operator(self):
        operator = self.env["res.users"].create({
            "name": "Op", "login": "op_create_lead_test",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])]})
        conv = self._new_conv(operator_id=operator.id)
        conv.action_create_lead()
        self.assertEqual(conv.lead_id.user_id, operator)

    def test_create_lead_backfills_the_history_into_the_new_lead(self):
        conv = self._new_conv()
        self._new_message(conv, body="Need 500 units")
        conv.action_create_lead()
        self.assertIn("Need 500 units", self._notes(conv.lead_id).body)

    def test_create_lead_refuses_when_one_is_already_linked(self):
        """Silently making a second lead would split one customer's history in
        two and leave the first lead looking abandoned."""
        conv = self._new_conv(lead_id=self.lead.id)
        with self.assertRaises(UserError):
            conv.action_create_lead()

    def test_create_lead_does_not_force_the_lead_type(self):
        """crm.lead computes `type` from whether the Leads feature is on; an
        installation that only uses opportunities would never show a record
        forced to "lead"."""
        conv = self._new_conv()
        conv.action_create_lead()
        expected = self.env["crm.lead"].default_get(["type"])["type"]
        self.assertEqual(conv.lead_id.type, expected)
