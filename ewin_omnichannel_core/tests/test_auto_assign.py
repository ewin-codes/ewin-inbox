from unittest.mock import patch

from odoo.tests import tagged
from .common import OmnichannelCase

_DELIVER = ("odoo.addons.ewin_omnichannel_core.services.routing_service."
            "RoutingService.deliver_outbound")


@tagged("post_install", "-at_install")
class TestAutoAssign(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "123"})
        self.conv = self.env["omnichannel.conversation"].create({
            "name": "Conv", "account_id": self.account.id,
            "identity_id": self.identity.id})
        self.other = self.env["res.users"].create(
            {"name": "Other Op", "login": "other_op_test"})

    def test_ensure_operator_assigns_current_user(self):
        self.assertFalse(self.conv.operator_id)
        self.conv._ensure_operator()
        self.assertEqual(self.conv.operator_id, self.env.user)
        self.assertEqual(self.conv.state, "open")

    def test_ensure_operator_keeps_existing(self):
        self.conv.operator_id = self.other
        self.conv._ensure_operator()
        self.assertEqual(self.conv.operator_id, self.other,
                         "must not steal a colleague's conversation")

    def test_reply_takes_conversation(self):
        with patch(_DELIVER):
            self.env["omnichannel.message.service"].create_outbound(
                self.conv, "hi there")
        self.assertEqual(self.conv.operator_id, self.env.user)
        self.assertEqual(self.conv.state, "open")

    def test_internal_note_does_not_take(self):
        with patch(_DELIVER):
            self.env["omnichannel.message.service"].create_outbound(
                self.conv, "private note", is_internal=True)
        self.assertFalse(self.conv.operator_id,
                         "an internal note is not a reply — no auto-assign")

    def test_notify_pushes_to_operator_bus(self):
        self.conv.operator_id = self.env.user
        with patch.object(type(self.env["bus.bus"]), "_sendone") as send:
            self.conv._notify_omni_event("message_received")
        self.assertTrue(send.called)
        _target, ntype, message = send.call_args[0]
        self.assertEqual(ntype, "omni.inbox")
        self.assertEqual(message["conversation_id"], self.conv.id)
        self.assertEqual(message["event"], "message_received")

    def test_notify_without_operator_only_refreshes_the_menu_badges(self):
        with patch.object(type(self.env["bus.bus"]), "_sendone") as send:
            self.conv._notify_omni_event("message_received")
        types = [call[0][1] for call in send.call_args_list]
        self.assertEqual(
            types, ["omni.menu.counters"],
            "nobody owns this conversation, so the only thing to say is that "
            "the unclaimed queue has grown")

    def test_member_sync_goes_through_add_members(self):
        """Membership must be granted with discuss.channel.add_members.

        It is the only path that pushes "discuss.channel/joined" to the new
        member, and that notification is what makes an already-open browser
        subscribe to the channel's bus. Creating the member row directly
        leaves the running session unsubscribed: no live message, no unread
        badge, no sound until a reload.
        """
        self.conv.operator_id = self.env.user
        channel = self.conv._ensure_discuss_channel()
        partner = self.env.user.partner_id
        member = channel.channel_member_ids.filtered(
            lambda m: m.partner_id == partner)
        self.assertTrue(member, "the operator must be a channel member")
        self.assertEqual(
            member.custom_notifications, "all",
            "the default 'mentions only' would silence the systray")

        # Drop the membership and re-sync, watching the bus.
        member.unlink()
        sent = []
        original = type(self.env["bus.bus"])._sendone

        def _spy(bus_self, target, notification_type, message):
            sent.append(notification_type)
            return original(bus_self, target, notification_type, message)

        with patch.object(type(self.env["bus.bus"]), "_sendone", _spy):
            self.conv._sync_channel_members()

        self.assertIn(
            "discuss.channel/joined", sent,
            "add_members must announce the join over the bus, otherwise an "
            "open browser never subscribes to this channel")

    def test_member_sync_is_idempotent(self):
        self.conv.operator_id = self.env.user
        channel = self.conv._ensure_discuss_channel()
        self.conv._sync_channel_members()
        self.conv._sync_channel_members()
        members = channel.channel_member_ids.filtered(
            lambda m: m.partner_id == self.env.user.partner_id)
        self.assertEqual(len(members), 1,
                         "repeated syncs must not duplicate the membership")
