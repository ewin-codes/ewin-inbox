from unittest.mock import patch

from odoo.tests import tagged

from .common import OmnichannelCase

OPERATOR_GROUP = "ewin_omnichannel_core.group_omni_operator"


@tagged("post_install", "-at_install")
class TestMenuCounters(OmnichannelCase):
    """The two numbers the Inbox and My Conversations menus wear.

    Grey on Inbox is the queue nobody has taken; red on My Conversations is
    what is addressed to the reader. Both are message counts, and both have to
    fall on their own — an operator who has to open a menu to find out whether
    it holds anything new is exactly the walk these badges exist to save.
    """

    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.service = self.env["omnichannel.routing.service"]
        # Both numbers count the whole database, so every assertion below is
        # about how far this test moved them — a suite that demanded an exact
        # total would pass on an empty database and nowhere else.
        self.before = self._counters()

    def _counters(self, user=None):
        model = self.env["omnichannel.conversation"]
        return (model.with_user(user) if user else model).omni_menu_counters()

    def _moved(self, user=None):
        now = self._counters(user)
        return {key: now[key] - self.before[key] for key in now}

    def _event(self, uid="123", ext="1", text="Hello"):
        return {
            "event_id": "test:update:%s:%s" % (uid, ext),
            "external_message_id": "%s-%s" % (uid, ext),
            "external_user": {"id": uid, "name": "Ivan Petrov",
                              "username": "ivan", "language_code": "ru"},
            "conversation": {"external_id": uid, "type": "private"},
            "message": {"type": "text", "text": text, "attachments": [],
                        "reply_to_external_message_id": None},
            "raw_payload": {},
        }

    def _inbound(self, uid="123", ext="1", text="Hello"):
        return self.service.process_event(
            self.account, self._event(uid, ext, text))

    def _operator(self, login):
        return self.env["res.users"].create({
            "name": login, "login": login,
            "groups_id": [(4, self.env.ref(OPERATOR_GROUP).id)]})

    # -- the grey badge: the unclaimed queue ------------------------------

    def test_unassigned_counts_every_inbound_message_nobody_has_taken(self):
        self._inbound(ext="1", text="first")
        self.assertEqual(self._moved()["unassigned"], 1)
        self._inbound(ext="2", text="second")
        self.assertEqual(
            self._moved()["unassigned"], 2,
            "the badge counts messages, not conversations")

    def test_taking_a_conversation_empties_the_grey_badge(self):
        conv = self._inbound().conversation_id
        conv.action_take()
        self.assertEqual(
            self._moved()["unassigned"], 0,
            "a conversation with an operator is no longer in the queue")

    def test_closing_a_conversation_empties_the_grey_badge(self):
        conv = self._inbound().conversation_id
        conv.write({"state": "closed"})
        self.assertEqual(self._moved()["unassigned"], 0)

    def test_outbound_messages_are_not_in_the_grey_badge(self):
        conv = self._inbound().conversation_id
        connector = self._fake_connector()
        with self._with_connector(connector):
            self.env["omnichannel.message.service"].create_outbound(conv, "hi")
        # Replying takes the conversation, so the queue is empty either way —
        # what this pins is that the reply itself was never counted.
        self.assertEqual(self._moved()["unassigned"], 0)
        conv.operator_id = False
        self.assertEqual(self._moved()["unassigned"], 1)

    def test_an_operator_is_told_only_what_their_rules_let_them_see(self):
        """The counts are read with the caller's own rights.

        The unclaimed queue is everyone's, and the record rule says so. A
        conversation a colleague has taken is not, and a badge that counted it
        would announce work its reader cannot open.
        """
        colleague = self._operator("counter_colleague")
        operator = self._operator("counter_operator")
        before = self._counters(operator)
        theirs = self._inbound(uid="222", ext="1").conversation_id
        self.assertEqual(
            self._counters(operator)["unassigned"], before["unassigned"] + 1,
            "while nobody has taken it, it is the whole floor's queue")
        theirs.operator_id = colleague
        self.env.invalidate_all()
        after = self._counters(operator)
        self.assertEqual(
            after["unassigned"], before["unassigned"],
            "taken by a colleague, it leaves this operator's badge")
        self.assertEqual(after["mine"], before["mine"])
        self.assertEqual(
            self.env["omnichannel.conversation"].with_user(
                operator).search_count([("id", "=", theirs.id)]), 0,
            "and the record rule really does keep it out of their reach")

    # -- the red badge: what is addressed to the reader --------------------

    def _mine_with_something_unread(self):
        conv = self._inbound(ext="1", text="first").conversation_id
        conv.operator_id = self.env.user
        conv._sync_channel_members()
        self._inbound(ext="2", text="second")
        self.env.invalidate_all()
        return conv

    def test_mine_adds_up_the_unread_counters_of_my_conversations(self):
        conv = self._mine_with_something_unread()
        self.assertTrue(
            conv.unread_count,
            "the fixture must leave something unread, or this proves nothing")
        self.assertEqual(self._moved()["mine"], conv.unread_count)

    def test_a_colleagues_conversation_is_not_in_my_red_badge(self):
        conv = self._mine_with_something_unread()
        conv.operator_id = self._operator("counter_other")
        self.env.invalidate_all()
        self.assertEqual(self._moved()["mine"], 0)

    def test_reading_a_conversation_empties_the_red_badge(self):
        conv = self._mine_with_something_unread()
        conv._mark_read()
        self.env.invalidate_all()
        self.assertEqual(self._moved()["mine"], 0)

    def test_a_closed_conversation_is_not_in_my_red_badge(self):
        conv = self._mine_with_something_unread()
        conv.write({"state": "closed"})
        self.env.invalidate_all()
        self.assertEqual(self._moved()["mine"], 0)

    # -- keeping the badges honest over the bus ---------------------------

    def _pings(self, func):
        """Run func and return the (target, payload) of every badge ping."""
        sent = []
        original = type(self.env["bus.bus"])._sendone

        def _spy(bus_self, target, notification_type, message):
            if notification_type == "omni.menu.counters":
                sent.append((target, message))
            return original(bus_self, target, notification_type, message)

        with patch.object(type(self.env["bus.bus"]), "_sendone", _spy):
            func()
        return sent

    def test_an_unassigned_message_reaches_the_whole_floor(self):
        """Nobody owns the queue, so there is no personal channel to aim at.

        ir.websocket subscribes every user to a bus channel per group they
        hold, which is how one ping refreshes every operator's grey badge.
        """
        conv = self._inbound().conversation_id
        self.assertFalse(conv.operator_id)
        pings = self._pings(lambda: conv._notify_omni_event("message_received"))
        self.assertEqual(len(pings), 1)
        target, payload = pings[0]
        self.assertEqual(target, self.env.ref(OPERATOR_GROUP))
        self.assertEqual(
            payload, {},
            "the ping carries no ids: it reaches operators whose record "
            "rules keep this conversation out of their own lists")

    def test_reading_pings_the_reader_alone(self):
        conv = self._mine_with_something_unread()
        pings = self._pings(conv._mark_read)
        self.assertEqual(len(pings), 1)
        self.assertEqual(pings[0][0], self.env.user.partner_id)

    def test_reading_pings_nobody_when_there_is_nothing_to_mark(self):
        """Reading is a Discuss channel membership.

        An operator who is not in the mirror has nothing to mark and nothing
        to say — a ping on every opened conversation would refresh every badge
        on the floor for a number that did not move.
        """
        conv = self._inbound().conversation_id
        stranger = self._operator("counter_stranger")
        self.assertFalse(
            conv.discuss_channel_id.channel_member_ids.filtered(
                lambda m: m.partner_id == stranger.partner_id))
        self.assertFalse(self._pings(conv.with_user(stranger)._mark_read))
