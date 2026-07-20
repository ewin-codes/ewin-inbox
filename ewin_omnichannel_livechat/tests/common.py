from odoo.tests import TransactionCase


class LivechatCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bridge_user = cls.env["res.users"].create({
            "name": "Bridge Bot", "login": "lc_bridge_bot"})
        cls.lc_channel = cls.env["im_livechat.channel"].create({
            "name": "Site Chat",
            "user_ids": [(6, 0, cls.bridge_user.ids)],
        })
        cls.omni_channel = cls.env["omnichannel.channel"].search(
            [("code", "=", "livechat")], limit=1)
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Site Chat account",
            "channel_id": cls.omni_channel.id,
            "livechat_channel_id": cls.lc_channel.id,
            "livechat_bridge_user_id": cls.bridge_user.id,
            "state": "connected",
        })

    def _make_session(self, visitor=None, anonymous_name="Visitor #1",
                      guest=None):
        members = [(0, 0, {"partner_id": self.bridge_user.partner_id.id})]
        if guest is not None:
            members.append((0, 0, {"guest_id": guest.id}))
        vals = {
            "name": "Session",
            "channel_type": "livechat",
            "livechat_channel_id": self.lc_channel.id,
            "livechat_operator_id": self.bridge_user.partner_id.id,
            "livechat_active": True,
            "anonymous_name": anonymous_name,
            "channel_member_ids": members,
        }
        if visitor is not None:
            vals["livechat_visitor_id"] = visitor.id
        return self.env["discuss.channel"].create(vals)

    def _visitor_post(self, channel, body="hello", author=None,
                      attachments=None):
        kwargs = {"body": body, "message_type": "comment",
                  "subtype_xmlid": "mail.mt_comment"}
        if author is not None:
            kwargs["author_id"] = author.id
        if attachments is not None:
            kwargs["attachment_ids"] = attachments.ids
        return channel.message_post(**kwargs)
