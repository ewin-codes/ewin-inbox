from odoo.tests import tagged

from .common import OmnichannelCrmCase


@tagged("post_install", "-at_install")
class TestLeadMerge(OmnichannelCrmCase):
    """Merging is an everyday pipeline action and it deletes leads behind the
    ORM's back: ``ondelete="set null"`` clears ``lead_id`` in the database, so
    the write hook that purges the history never runs. Unless the bridge
    carries the link across, the conversation ends up linked to nothing while
    its texts sit on the survivor with no way left to remove them."""

    def setUp(self):
        super().setUp()
        duplicate = self.env["crm.lead"].with_context(
            mail_create_nolog=True).create({"name": "Bulk order (again)"})
        self.pair = self.lead | duplicate
        # Which lead survives is Odoo's call, made on confidence rather than
        # on the order given; ask it instead of assuming, since the test is
        # about the one that dies.
        self.survivor = self.pair._sort_by_confidence_level(reverse=True)[0]
        self.merged_away = self.pair - self.survivor

    def test_a_merge_moves_the_link_to_the_surviving_lead(self):
        conv = self._new_conv(lead_id=self.merged_away.id)
        self.pair.merge_opportunity()
        self.assertFalse(self.merged_away.exists())
        self.assertEqual(conv.lead_id, self.survivor)

    def test_a_merge_leaves_one_copy_of_each_message_on_the_survivor(self):
        """Odoo moves the copies itself, so re-pointing the link afterwards
        has to find them already there rather than post a second set."""
        conv = self._new_conv(lead_id=self.merged_away.id)
        message = self._new_message(conv, body="Need 500 units")
        self.history.mirror(message)
        self.pair.merge_opportunity()
        copies = self._history_notes(self.survivor)
        self.assertEqual(len(copies), 1)
        self.assertIn("Need 500 units", copies.body)
        self.assertEqual(message.history_message_ids, copies)

    def test_an_archived_conversation_follows_the_merge_too(self):
        """Archiving does not detach a conversation from its history, so a
        merge must not be the thing that does — its copies move to the survivor
        whether the search sees it or not."""
        conv = self._new_conv(lead_id=self.merged_away.id, active=False)
        self.pair.merge_opportunity()
        self.assertEqual(conv.lead_id, self.survivor)

    def test_the_history_of_a_merged_lead_can_still_be_unlinked(self):
        """What keeping the ledger honest buys: after a merge the operator can
        still detach the conversation and take the texts with it."""
        conv = self._new_conv(lead_id=self.merged_away.id)
        self.history.mirror(self._new_message(conv, body="Need 500 units"))
        self.pair.merge_opportunity()
        conv.lead_id = False
        self.assertFalse(self._history_notes(self.survivor))
