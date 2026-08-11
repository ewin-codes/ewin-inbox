from odoo.tests import tagged

from .common import OmnichannelCrmCase


@tagged("post_install", "-at_install")
class TestLinkWizard(OmnichannelCrmCase):
    def _wizard(self, convs):
        return self.env["omnichannel.conversation.link.wizard"].create({
            "lead_id": self.lead.id,
            "conversation_ids": [(6, 0, convs.ids)]})

    def test_the_button_hands_the_lead_to_the_wizard(self):
        action = self.lead.action_omni_link_conversations()
        self.assertEqual(
            action["res_model"], "omnichannel.conversation.link.wizard")
        self.assertEqual(action["target"], "new")
        self.assertEqual(action["context"]["default_lead_id"], self.lead.id)

    def test_confirming_links_every_selected_conversation(self):
        first = self._new_conv()
        second = self._new_conv(name="Second")
        result = self._wizard(first | second).action_confirm()
        self.assertEqual(result["type"], "ir.actions.act_window_close")
        self.assertEqual(first.lead_id, self.lead)
        self.assertEqual(second.lead_id, self.lead)

    def test_confirming_backfills_the_history_of_each_conversation(self):
        """Linking through the wizard has to reach the same code path as the
        form field, or the lead ends up with links but no texts."""
        conv = self._new_conv()
        self._new_message(conv, body="Need 500 units")
        self._wizard(conv).action_confirm()
        self.assertIn("Need 500 units", self._notes(self.lead).body)

    def test_the_wizard_knows_the_lead_contact_for_its_default_filter(self):
        """The picker preselects the lead's own contact; without the related
        field the form has nothing to filter on."""
        self.lead.partner_id = self.partner
        wizard = self._wizard(self._new_conv())
        self.assertEqual(wizard.lead_partner_id, self.partner)
