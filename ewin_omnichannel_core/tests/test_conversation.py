from odoo.tests import tagged
from odoo.tools import file_open

from ..models.omnichannel_conversation import (
    CHANNEL_ICON_DEFAULT, CHANNEL_ICONS, CHANNEL_IMAGE_ICONS)
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
            "groups_id": [(4, self.env.ref(
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

    def test_channel_icon_uses_the_brand_image_where_fontawesome_has_none(self):
        """Odoo bundles FontAwesome 4.7, which has no fa-viber: the glyph is
        silently blank, so the brand PNG has to stand in."""
        viber = self.env["omnichannel.channel"].search(
            [("code", "=", "viber")], limit=1) or \
            self.env["omnichannel.channel"].create(
                {"name": "Viber", "code": "viber"})
        acc = self.env["omnichannel.account"].create(
            {"name": "ViberBot", "channel_id": viber.id})
        ident = self.env["omnichannel.identity"].create(
            {"account_id": acc.id, "external_id": "10"})
        conv = self.env["omnichannel.conversation"].create({
            "name": "C", "account_id": acc.id, "identity_id": ident.id})
        for markup in (conv.channel_icon, conv.customer_label):
            self.assertNotIn("fa-viber", markup)
            self.assertIn(
                "/ewin_omnichannel_core/static/src/img/channel_viber.png",
                markup)

    def test_every_glyph_referenced_exists_in_the_bundled_fontawesome(self):
        """A class FontAwesome does not carry is not an error, it is a blank
        cell — which is exactly how ``fa-viber`` shipped. Pin every glyph we
        name against the stylesheet Odoo actually serves."""
        path = "web/static/src/libs/fontawesome/css/font-awesome.css"
        try:
            with file_open(path) as fh:
                css = fh.read()
        except (FileNotFoundError, OSError):
            self.skipTest("bundled FontAwesome not found at %s" % path)
        for glyph, _colour in [*CHANNEL_ICONS.values(), CHANNEL_ICON_DEFAULT]:
            self.assertIn(
                ".%s:before" % glyph, css,
                "%s is not in the bundled FontAwesome and would render "
                "as an empty icon" % glyph)

    def test_every_connector_channel_has_its_own_brand_marker(self):
        """A connector that forgets to register an icon would fall through to
        the generic bubble and be indistinguishable from the other channels."""
        channels = self.env["omnichannel.channel"].search(
            [("connector_module", "!=", False)])
        for channel in channels:
            self.assertTrue(
                channel.code in CHANNEL_ICONS
                or channel.code in CHANNEL_IMAGE_ICONS,
                "channel %r has no brand marker of its own" % channel.code)
        for code in CHANNEL_IMAGE_ICONS:
            # the PNG the markup points at has to actually be on disk
            self.assertTrue(
                self.env["omnichannel.conversation"]._channel_avatar_b64(code),
                "no brand PNG shipped for %r" % code)

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
