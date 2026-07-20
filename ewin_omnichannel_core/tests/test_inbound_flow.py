from odoo.tests import tagged
from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestInboundFlow(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})

    def _event(self, uid="123", name="Ivan Petrov", text="Hello"):
        return {
            "event_id": f"test:update:{uid}",
            "external_message_id": "987",
            "external_user": {"id": uid, "name": name,
                              "username": "ivan", "language_code": "ru"},
            "conversation": {"external_id": uid, "type": "private"},
            "message": {"type": "text", "text": text, "attachments": [],
                        "reply_to_external_message_id": None},
            "raw_payload": {},
        }

    def test_new_customer_creates_identity_partner_conversation(self):
        svc = self.env["omnichannel.routing.service"]
        msg = svc.process_event(self.account, self._event())
        self.assertEqual(msg.direction, "inbound")
        self.assertEqual(msg.conversation_id.identity_id.external_id, "123")
        self.assertTrue(msg.conversation_id.partner_id)
        self.assertEqual(msg.conversation_id.partner_id.name, "Ivan Petrov")

    def test_inbound_mirror_author_is_customer(self):
        svc = self.env["omnichannel.routing.service"]
        msg = svc.process_event(self.account, self._event())
        self.assertTrue(msg.mail_message_id)
        self.assertEqual(msg.mail_message_id.author_id, msg.conversation_id.partner_id)
        self.assertNotEqual(msg.mail_message_id.author_id, self.env.user.partner_id)

    def test_duplicate_external_message_id_dedup(self):
        svc = self.env["omnichannel.routing.service"]
        ev = self._event()
        msg1 = svc.process_event(self.account, ev)
        msg2 = svc.process_event(self.account, ev)
        self.assertEqual(msg1, msg2)
        self.assertEqual(
            self.env["omnichannel.message"].search_count(
                [("conversation_id", "=", msg1.conversation_id.id),
                 ("direction", "=", "inbound")]), 1)

    def test_repeat_message_reuses_identity_and_conversation(self):
        svc = self.env["omnichannel.routing.service"]
        msg1 = svc.process_event(self.account, self._event(text="first"))
        msg2 = svc.process_event(self.account, self._event(text="second"))
        self.assertEqual(msg1.conversation_id, msg2.conversation_id)
        self.assertEqual(
            self.env["res.partner"].search_count(
                [("omni_external_id", "=", "123")]), 1)

    def test_partner_name_fallback_username(self):
        svc = self.env["omnichannel.routing.service"]
        ev = self._event(name=None)
        msg = svc.process_event(self.account, ev)
        self.assertEqual(msg.conversation_id.partner_id.name,
                         f"{self.channel.name} @ivan")

    def test_unsupported_type_marked(self):
        svc = self.env["omnichannel.routing.service"]
        ev = self._event()
        ev["message"]["type"] = "poll"  # a type we do not handle
        msg = svc.process_event(self.account, ev)
        self.assertEqual(msg.message_type, "unsupported")

    def test_extended_media_type_preserved(self):
        svc = self.env["omnichannel.routing.service"]
        for idx, mtype in enumerate(
                ("voice", "audio", "video", "location", "contact", "sticker")):
            ev = self._event()
            ev["external_message_id"] = f"media{idx}"
            ev["message"]["type"] = mtype
            msg = svc.process_event(self.account, ev)
            self.assertEqual(msg.message_type, mtype)

    def test_sparse_repeat_payload_preserves_identity_profile(self):
        svc = self.env["omnichannel.routing.service"]
        msg1 = svc.process_event(self.account, self._event(text="first"))
        identity = msg1.conversation_id.identity_id
        self.assertEqual(identity.display_name, "Ivan Petrov")
        self.assertEqual(identity.username, "ivan")
        first_seen_at = identity.last_seen_at

        sparse_event = {
            "event_id": "test:update:123:2",
            "external_message_id": "988",
            "external_user": {"id": "123"},
            "conversation": {"external_id": "123", "type": "private"},
            "message": {"type": "text", "text": "second", "attachments": [],
                        "reply_to_external_message_id": None},
            "raw_payload": {},
        }
        svc.process_event(self.account, sparse_event)
        identity.invalidate_recordset()

        self.assertEqual(identity.display_name, "Ivan Petrov")
        self.assertEqual(identity.username, "ivan")
        self.assertTrue(identity.last_seen_at)
        self.assertGreaterEqual(identity.last_seen_at, first_seen_at)

    def test_thread_reference_resolves_existing_conversation(self):
        svc = self.env["omnichannel.routing.service"]
        first_ev = self._event(text="first")  # sender uid 123
        first_ev["external_message_id"] = "m1"
        first = svc.process_event(self.account, first_ev)
        # a DIFFERENT sender (no shared identity, no open-conversation match)
        # whose message references the first must thread into it via
        # thread_reference, not spawn a new conversation.
        ev = self._event(text="reply", uid="999")
        ev["external_message_id"] = "m2"
        ev["thread_reference"] = ["m1"]
        second = svc.process_event(self.account, ev)
        self.assertEqual(second.conversation_id, first.conversation_id)
        # negative control: a different sender with no thread_reference gets
        # its own conversation (proves the match above came from threading).
        ev2 = self._event(text="other", uid="888")
        ev2["external_message_id"] = "m3"
        other = svc.process_event(self.account, ev2)
        self.assertNotEqual(other.conversation_id, first.conversation_id)
