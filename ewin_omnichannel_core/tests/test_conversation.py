import re
from pathlib import Path

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tools import file_open

from ..models.omnichannel_conversation import (
    CHANNEL_AVATAR_CODES, CHANNEL_AVATAR_URL, CHANNEL_ICON_DEFAULT)
from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestConversation(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "123"})

    def _new_conv(self):
        return self.env["omnichannel.conversation"].create({
            "name": "Conv", "account_id": self.account.id,
            "identity_id": self.identity.id})

    def test_take_sets_operator_and_open(self):
        conv = self._new_conv()
        conv.action_take()
        self.assertEqual(conv.operator_id, self.env.user)
        self.assertEqual(conv.state, "open")

    def test_close_and_reopen(self):
        conv = self._new_conv()
        conv.action_close()
        self.assertEqual(conv.state, "closed")
        self.assertTrue(conv.closed_at)
        conv.action_reopen()
        self.assertEqual(conv.state, "open")
        self.assertFalse(conv.closed_at)

    def test_set_pending_refuses_a_closed_conversation(self):
        """Pending on a closed thread would leave closed_at, closed_by and
        the close reason describing a closure the state no longer shows —
        the way back from Closed is Re-open."""
        conv = self._new_conv()
        conv.action_close()
        with self.assertRaises(UserError):
            conv.action_set_pending()
        self.assertEqual(conv.state, "closed")

    def test_wait_for_customer_is_hidden_once_closed(self):
        view = self.env.ref("ewin_omnichannel_core.view_conversation_form")
        button = view.get_combined_arch()
        self.assertRegex(
            button,
            r'name="action_set_pending"[^>]*invisible="[^"]*closed')

    def test_ensure_discuss_channel(self):
        conv = self._new_conv()
        ch = conv._ensure_discuss_channel()
        self.assertTrue(ch)
        self.assertEqual(ch.omni_conversation_id, conv)
        # idempotent
        self.assertEqual(conv._ensure_discuss_channel(), ch)

    def test_take_joins_channel(self):
        conv = self._new_conv()
        conv.action_take()
        # the operator becomes a member of the mirror channel so the Discuss
        # systray notifies them of new inbound messages
        channel = conv.discuss_channel_id
        self.assertTrue(channel)
        self.assertIn(
            self.env.user.partner_id, channel.channel_member_ids.partner_id)

    def test_unread_count_follows_discuss_and_mark_read(self):
        # unread_count derives from the current user's Discuss member seen state:
        # a mirrored inbound raises it, _mark_read clears it.
        operator = self.env["res.users"].create({
            "name": "Op2", "login": "op2_unread",
            "group_ids": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        conv = self._new_conv()
        conv.operator_id = operator
        conv._sync_channel_members()
        conv_op = conv.with_user(operator)
        self.env["omnichannel.message.service"].create_inbound(
            conv, {"text": "hello", "type": "text",
                   "external_message_id": "u1"})
        conv_op.invalidate_recordset(["unread_count"])
        self.assertGreater(conv_op.unread_count, 0)
        conv_op._mark_read()
        conv_op.invalidate_recordset(["unread_count"])
        self.assertEqual(conv_op.unread_count, 0)

    def test_sync_channel_members_idempotent(self):
        conv = self._new_conv()
        conv.operator_id = self.env.user
        conv._sync_channel_members()
        conv._sync_channel_members()
        channel = conv.discuss_channel_id
        members = channel.channel_member_ids.filtered(
            lambda m: m.partner_id == self.env.user.partner_id)
        self.assertEqual(len(members), 1)

    def test_attachment_preview_image_vs_file(self):
        conv = self._new_conv()
        img = self.env["ir.attachment"].create({
            "name": "pic.png", "mimetype": "image/png", "raw": b"hi"})
        doc = self.env["ir.attachment"].create({
            "name": "report.pdf", "mimetype": "application/pdf", "raw": b"hi"})
        msg = self.env["omnichannel.message"].create({
            "conversation_id": conv.id, "direction": "inbound",
            "sender_type": "customer", "attachment_ids": [(6, 0, (img | doc).ids)]})
        self.assertTrue(msg.has_attachments)
        preview = msg.attachment_preview
        self.assertIn("/web/image/%s" % img.id, preview)  # image -> thumbnail
        self.assertIn("report.pdf", preview)  # file -> chip with name
        self.assertIn("/web/content/%s?download=true" % doc.id, preview)

    def test_attachment_preview_escapes_name(self):
        conv = self._new_conv()
        evil = self.env["ir.attachment"].create({
            "name": "<script>x</script>.pdf", "mimetype": "application/pdf",
            "raw": b"hi"})
        msg = self.env["omnichannel.message"].create({
            "conversation_id": conv.id, "direction": "inbound",
            "sender_type": "customer", "attachment_ids": [(6, 0, evil.ids)]})
        # the raw tag must be escaped, not embedded as live markup
        self.assertNotIn("<script>", msg.attachment_preview)
        self.assertIn("&lt;script&gt;", msg.attachment_preview)

    def test_channel_icon_maps_by_code(self):
        tg = self.env["omnichannel.channel"].search(
            [("code", "=", "telegram")], limit=1) or \
            self.env["omnichannel.channel"].create(
                {"name": "Telegram", "code": "telegram"})
        acc = self.env["omnichannel.account"].create(
            {"name": "TgBot", "channel_id": tg.id})
        ident = self.env["omnichannel.identity"].create(
            {"account_id": acc.id, "external_id": "9"})
        conv = self.env["omnichannel.conversation"].create({
            "name": "C", "account_id": acc.id, "identity_id": ident.id})
        self.assertIn(CHANNEL_AVATAR_URL % "telegram", conv.channel_icon)
        # unknown channel code falls back to a generic icon, never blank
        conv2 = self._new_conv()  # uses the "test" channel
        self.assertIn(
            'data-icon="%s"' % CHANNEL_ICON_DEFAULT[0], conv2.channel_icon)

    def test_the_customer_label_carries_the_brand_marker(self):
        viber = self.env["omnichannel.channel"].search(
            [("code", "=", "viber")], limit=1) or             self.env["omnichannel.channel"].create(
                {"name": "Viber", "code": "viber"})
        acc = self.env["omnichannel.account"].create(
            {"name": "ViberBot", "channel_id": viber.id})
        ident = self.env["omnichannel.identity"].create(
            {"account_id": acc.id, "external_id": "10"})
        conv = self.env["omnichannel.conversation"].create({
            "name": "C", "account_id": acc.id, "identity_id": ident.id})
        for markup in (conv.channel_icon, conv.customer_label):
            self.assertIn(CHANNEL_AVATAR_URL % "viber", markup)

    def test_every_icon_named_is_in_odoos_icon_subset(self):
        """Odoo ships a subset of Material Symbols, and a name outside it is
        not an error but a blank where the icon should be. Pin every name this
        module draws against the list the subset is built from."""
        path = "web/tooling/icons/icons_wishlist.txt"
        try:
            with file_open(path) as fh:
                subset = set(fh.read().split())
        except (FileNotFoundError, OSError):
            self.skipTest("Odoo's icon list not found at %s" % path)
        module = Path(__file__).resolve().parents[1]
        names = {CHANNEL_ICON_DEFAULT[0]}
        for source in [*module.rglob("*.xml"), *module.rglob("*.py")]:
            if "tests" in source.parts:
                continue
            text = source.read_text(encoding="utf-8")
            # data-icon="..." and a button's icon="..." alike
            names.update(re.findall(r'icon="([a-z_]+)"', text))
        self.assertTrue(names - {CHANNEL_ICON_DEFAULT[0]},
                        "the scan found no icons: the pattern is broken")
        self.assertFalse(
            names - subset,
            "not in Odoo's icon subset, so drawn as a blank")

    def test_every_connector_channel_has_its_own_brand_marker(self):
        """A connector that forgets to ship a brand image would fall through
        to the generic bubble and be indistinguishable from the others."""
        channels = self.env["omnichannel.channel"].search(
            [("connector_module", "!=", False)])
        for channel in channels:
            self.assertIn(
                channel.code, CHANNEL_AVATAR_CODES,
                "channel %r has no brand marker of its own" % channel.code)

    def test_every_connector_channel_has_a_discuss_avatar(self):
        """The Discuss sidebar draws the mirror channel's avatar, not the list
        icon: a channel without a brand PNG shows up there as a generic '#',
        and every customer on it looks like an ordinary team channel."""
        channels = self.env["omnichannel.channel"].search(
            [("connector_module", "!=", False)])
        for channel in channels:
            self.assertTrue(
                self.env["omnichannel.conversation"]._channel_avatar(
                    channel.code),
                "no Discuss avatar shipped for %r" % channel.code)

    def test_send_shortcut_reads_config(self):
        conv = self._new_conv()
        # default when unset
        self.env["ir.config_parameter"].sudo().set_str(
            "ewin_omnichannel.send_shortcut", "")
        conv.invalidate_recordset(["send_shortcut"])
        self.assertEqual(conv.send_shortcut, "ctrl_enter")
        # follows the configured value
        self.env["ir.config_parameter"].sudo().set_str(
            "ewin_omnichannel.send_shortcut", "enter")
        conv.invalidate_recordset(["send_shortcut"])
        self.assertEqual(conv.send_shortcut, "enter")

    def test_no_attachments_preview_falsy(self):
        conv = self._new_conv()
        msg = self.env["omnichannel.message"].create({
            "conversation_id": conv.id, "direction": "inbound",
            "sender_type": "customer", "body": "hi"})
        self.assertFalse(msg.has_attachments)
        self.assertFalse(msg.attachment_preview)
