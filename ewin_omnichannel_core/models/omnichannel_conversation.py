import base64

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.tools import file_open

# Channel code -> (fontawesome class, brand colour) for the list icon.
CHANNEL_ICONS = {
    "telegram": ("fa-telegram", "#29a9eb"),
    "viber": ("fa-viber", "#7360f2"),
    "email": ("fa-envelope", "#d44638"),
}
CHANNEL_ICON_DEFAULT = ("fa-comments-o", "#6c757d")

# Channel codes that ship a brand avatar PNG under static/src/img, used as the
# mirrored Discuss channel's avatar so the source is recognisable in the
# Discuss sidebar (which shows an avatar, not the FontAwesome list icon).
CHANNEL_AVATAR_CODES = ("telegram", "viber", "email")


class OmnichannelConversation(models.Model):
    _name = "omnichannel.conversation"
    _description = "Omnichannel Conversation"
    _inherit = ["mail.thread"]
    _order = "last_message_at desc, id desc"

    name = fields.Char(required=True, default="New")
    subject = fields.Char(
        help="Thread subject for channels that carry one (e.g. the email "
             "Subject line). Empty for chat channels, whose 'name' is the "
             "customer. Set once from the first inbound message.")
    account_id = fields.Many2one(
        "omnichannel.account", required=True, ondelete="restrict", index=True)
    channel_id = fields.Many2one(related="account_id.channel_id", store=True)
    channel_icon = fields.Html(
        compute="_compute_channel_icon", sanitize=False, string="Channel")
    send_shortcut = fields.Char(
        compute="_compute_send_shortcut",
        help="Composer send shortcut ('enter' or 'ctrl_enter'), from settings.")
    compose_hint = fields.Char(
        compute="_compute_compose_hint",
        help="Channel-aware heading for the reply composer.")
    customer_label = fields.Html(
        compute="_compute_customer_label", sanitize=False, string="Customer",
        help="Channel icon + customer name + unread badge for the list.")
    identity_id = fields.Many2one(
        "omnichannel.identity", required=True, ondelete="restrict", index=True)
    partner_id = fields.Many2one("res.partner", index=True)
    company_id = fields.Many2one(
        related="account_id.company_id", store=True, index=True)
    operator_id = fields.Many2one("res.users", string="Operator", index=True)
    team_id = fields.Many2one("omnichannel.team")
    state = fields.Selection(
        [("new", "New"), ("open", "Open"),
         ("pending", "Pending Customer"), ("closed", "Closed")],
        default="new", required=True, index=True)
    priority = fields.Selection(
        [("0", "Normal"), ("1", "High"), ("2", "Urgent")], default="0")
    last_message_at = fields.Datetime(index=True)
    last_customer_message_at = fields.Datetime()
    last_operator_message_at = fields.Datetime()
    first_customer_message_at = fields.Datetime(readonly=True, index=True)
    first_operator_message_at = fields.Datetime(readonly=True)
    first_response_seconds = fields.Integer(
        compute="_compute_first_response_seconds", store=True,
        string="First response (s)",
        help="Seconds between the customer's first message and the operator's "
             "first reply. 0 until the operator has responded.")
    unread_count = fields.Integer(
        compute="_compute_unread_count", string="Unread",
        help="Messages the current user has not yet read in the linked Discuss "
             "channel. Single source of truth so reading anywhere (Discuss app, "
             "chat window, embedded thread) clears the list badge.")
    discuss_channel_id = fields.Many2one("discuss.channel", copy=False)
    closed_at = fields.Datetime(readonly=True)
    closed_by = fields.Many2one("res.users", readonly=True)
    tag_ids = fields.Many2many("omnichannel.tag", string="Tags")
    omni_message_ids = fields.One2many(
        "omnichannel.message", "conversation_id", string="Omnichannel Messages")
    active = fields.Boolean(default=True)
    composer_body = fields.Text(copy=False)
    composer_is_internal = fields.Boolean(string="Internal note", copy=False)
    composer_attachment_ids = fields.Many2many(
        "ir.attachment", "omni_conv_composer_att_rel", "conv_id", "att_id",
        string="Attachments", copy=False)

    @api.depends_context("uid")
    @api.depends("discuss_channel_id.channel_member_ids.message_unread_counter")
    def _compute_unread_count(self):
        partner = self.env.user.partner_id
        for conv in self:
            member = conv.discuss_channel_id.channel_member_ids.filtered(
                lambda m: m.partner_id == partner)[:1]
            conv.unread_count = member.message_unread_counter if member else 0

    @api.depends("first_customer_message_at", "first_operator_message_at")
    def _compute_first_response_seconds(self):
        for conv in self:
            start = conv.first_customer_message_at
            end = conv.first_operator_message_at
            if start and end and end >= start:
                conv.first_response_seconds = int((end - start).total_seconds())
            else:
                conv.first_response_seconds = 0

    def _compute_send_shortcut(self):
        value = self.env["ir.config_parameter"].sudo().get_param(
            "ewin_omnichannel.send_shortcut", "ctrl_enter")
        for conv in self:
            conv.send_shortcut = value

    @api.depends("channel_id.name")
    def _compute_compose_hint(self):
        for conv in self:
            channel = conv.channel_id.name or _("the customer's channel")
            conv.compose_hint = _("Reply to customer in %s", channel)

    @api.depends_context("uid")
    @api.depends("channel_id.code", "channel_id.name", "partner_id",
                 "identity_id", "name", "unread_count")
    def _compute_customer_label(self):
        for conv in self:
            code = conv.channel_id.code or ""
            icon, color = CHANNEL_ICONS.get(code, CHANNEL_ICON_DEFAULT)
            chan = escape(conv.channel_id.name or code or "Channel")
            name = escape(
                conv.partner_id.display_name
                or conv.identity_id.display_name or conv.name or "Unknown")
            parts = [
                Markup('<i class="fa %s" style="color:%s;'
                       'line-height:1;font-size:15px" title="%s"></i>') % (
                    icon, color, chan),
                Markup('<span>%s</span>') % name,
            ]
            if conv.unread_count:
                parts.append(Markup(
                    '<span class="badge rounded-pill text-bg-danger" '
                    'style="line-height:1">%s</span>') % conv.unread_count)
            conv.customer_label = Markup(
                '<span class="o_omni_customer" style="display:inline-flex;'
                'align-items:center;gap:6px">%s</span>') % Markup("").join(parts)

    @api.depends("channel_id", "channel_id.code", "channel_id.name")
    def _compute_channel_icon(self):
        for conv in self:
            code = conv.channel_id.code or ""
            icon, color = CHANNEL_ICONS.get(code, CHANNEL_ICON_DEFAULT)
            label = escape(conv.channel_id.name or code or "Channel")
            conv.channel_icon = Markup(
                '<i class="fa %s" style="color:%s;font-size:16px" '
                'title="%s" role="img" aria-label="%s"></i>') % (
                icon, color, label, label)

    @api.model
    def _channel_avatar_b64(self, code):
        """Return the base64 brand avatar for a channel code, or False."""
        if code not in CHANNEL_AVATAR_CODES:
            return False
        try:
            with file_open(
                "ewin_omnichannel_core/static/src/img/channel_%s.png" % code,
                "rb") as fh:
                return base64.b64encode(fh.read())
        except (FileNotFoundError, OSError):
            return False

    def _ensure_discuss_channel(self):
        """Create the linked discuss.channel on first need."""
        self.ensure_one()
        if self.discuss_channel_id:
            return self.discuss_channel_id
        partners = self.env["res.users"]
        if self.operator_id:
            partners |= self.operator_id
        vals = {
            "name": self.name or _("Conversation"),
            "channel_type": "channel",
            "channel_member_ids": [
                (0, 0, {"partner_id": pid})
                for pid in partners.mapped("partner_id").ids
            ],
        }
        avatar = self._channel_avatar_b64(self.channel_id.code)
        if avatar:
            vals["image_128"] = avatar
        channel = self.env["discuss.channel"].create(vals)
        self.discuss_channel_id = channel
        channel.omni_conversation_id = self.id
        return channel

    def _sync_channel_members(self):
        """Ensure the assigned operator is a member of the mirror channel so
        Odoo's Discuss systray raises the native unread badge / notification
        on new inbound messages (§ notifications)."""
        for conv in self:
            if not conv.operator_id:
                continue
            channel = conv._ensure_discuss_channel()
            partner = conv.operator_id.partner_id
            if not partner:
                continue
            member = channel.channel_member_ids.filtered(
                lambda m: m.partner_id == partner)
            if not member:
                member = self.env["discuss.channel.member"].create({
                    "channel_id": channel.id, "partner_id": partner.id})
            # notify on every message (default channel setting is mentions-only,
            # which is why the operator got no push/sound) so the Discuss systray
            # raises the badge + sound like a direct message.
            if member.custom_notifications != "all":
                member.custom_notifications = "all"

    def _mark_read(self):
        """Mark the linked Discuss channel as read for the current user, which
        drives unread_count (native member seen state). Reading anywhere else
        (Discuss app, chat window) clears it the same way."""
        partner = self.env.user.partner_id
        for conv in self:
            channel = conv.discuss_channel_id
            if not channel:
                continue
            member = channel.channel_member_ids.filtered(
                lambda m: m.partner_id == partner)
            if not member or not channel.message_ids:
                continue
            member._mark_as_read(max(channel.message_ids.ids))

    @api.model
    def action_seen(self, conversation_ids):
        """Called by the thread widget when a conversation is opened: opening it
        counts as reading, so the unread badge in the list is cleared."""
        self.browse(conversation_ids).exists()._mark_read()
        return True

    def action_take(self):
        for conv in self:
            conv.write({"operator_id": self.env.uid,
                        "state": "open" if conv.state == "new" else conv.state})
            conv._sync_channel_members()
            conv.message_post(body=_("Taken by %s", self.env.user.name))
            conv._notify_omni_event("conversation_assigned")

    def action_set_pending(self):
        self.write({"state": "pending"})

    def action_close(self):
        self.write({"state": "closed", "closed_at": fields.Datetime.now(),
                    "closed_by": self.env.uid})
        for conv in self:
            conv._notify_omni_event("conversation_closed")

    def action_reopen(self):
        self.write({"state": "open", "closed_at": False, "closed_by": False})

    def _notify_omni_event(self, event_name, payload=None):
        """Hook point for future automations/CRM/AI. No-op body in MVP."""
        self.ensure_one()
        return True

    def action_send_reply(self):
        self.ensure_one()
        body = (self.composer_body or "").strip()
        attachments = self.composer_attachment_ids
        if not body and not attachments:
            return
        self.env["omnichannel.message.service"].create_outbound(
            self, body, is_internal=self.composer_is_internal,
            attachments=attachments)
        self._mark_read()
        self.composer_body = False
        # keep composer_is_internal as-is: an operator writing internal notes
        # usually writes several in a row, so the toggle stays on until they
        # turn it off themselves.
        self.composer_attachment_ids = [(5, 0, 0)]
