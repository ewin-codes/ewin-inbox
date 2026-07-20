from odoo.tests import tagged

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
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])]})
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
            "name": "pic.png", "mimetype": "image/png", "datas": b"aGk="})
        doc = self.env["ir.attachment"].create({
            "name": "report.pdf", "mimetype": "application/pdf", "datas": b"aGk="})
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
            "datas": b"aGk="})
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
        self.assertIn("fa-telegram", conv.channel_icon)
        # unknown channel code falls back to a generic icon, never blank
        conv2 = self._new_conv()  # uses the "test" channel
        self.assertIn("fa-comments-o", conv2.channel_icon)

    def test_send_shortcut_reads_config(self):
        conv = self._new_conv()
        # default when unset
        self.env["ir.config_parameter"].sudo().set_param(
            "ewin_omnichannel.send_shortcut", "")
        conv.invalidate_recordset(["send_shortcut"])
        self.assertEqual(conv.send_shortcut, "ctrl_enter")
        # follows the configured value
        self.env["ir.config_parameter"].sudo().set_param(
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
