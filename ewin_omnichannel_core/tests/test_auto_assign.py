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

    def test_notify_is_noop_without_operator(self):
        with patch.object(type(self.env["bus.bus"]), "_sendone") as send:
            self.conv._notify_omni_event("message_received")
        self.assertFalse(
            send.called, "no operator to notify -> no bus traffic")
