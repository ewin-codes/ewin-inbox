import base64

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.tools import file_open

# Channel code -> (fontawesome class, brand colour) for the list icon.
CHANNEL_ICONS = {
    "telegram": ("fa-telegram", "#29a9eb"),
    "whatsapp": ("fa-whatsapp", "#25d366"),
    "instagram": ("fa-instagram", "#e1306c"),
    "email": ("fa-envelope", "#d44638"),
    "livechat": ("fa-comments", "#00a09d"),
}
CHANNEL_ICON_DEFAULT = ("fa-comments-o", "#6c757d")

# Channel codes that ship a brand PNG under static/src/img. It is the mirrored
# Discuss channel's avatar, so the source is recognisable in the Discuss
# sidebar (which shows an avatar, not the FontAwesome list icon).
CHANNEL_AVATAR_CODES = ("telegram", "viber", "email", "messenger")
CHANNEL_AVATAR_URL = "/ewin_omnichannel_core/static/src/img/channel_%s.png"

# Channel codes drawn from that brand PNG in the lists too, because Odoo
# bundles FontAwesome 4.7 and it carries no glyph for Viber or Messenger — an
# <i class="fa fa-viber"> is a valid-looking tag that renders as a blank cell.
CHANNEL_IMAGE_ICONS = ("viber", "messenger")

# How hard the Close button asks why: "off" | "optional" | "required".
CLOSE_REASON_POLICY_PARAM = "ewin_omnichannel.close_reason_policy"


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
        compute="_compute_channel_icon", sanitize=False, string="Channel Icon")
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
    close_reason_id = fields.Many2one(
        "omnichannel.close.reason", string="Close Reason", readonly=True,
        index=True, copy=False, ondelete="restrict",
        help="Why the conversation was closed. Cleared when it is reopened; "
             "the chatter keeps the history.")
    close_note = fields.Text(
        string="Close Comment", readonly=True, copy=False,
        help="The operator's own words about the closure, for anything the "
             "preset reasons do not cover.")
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

    @api.model
    def _history_link_fields(self):
        """Fields whose change re-points where this conversation's history is
        mirrored. Bridge modules extend the list (the CRM bridge adds
        ``lead_id``), which is what keeps ``write`` free of any knowledge of
        which links exist."""
        return ["partner_id"]

    def _history_targets(self):
        """The mail.thread records whose chatter must hold this conversation.

        A *list* of singleton records, not a recordset: a contact and a lead
        are different models and cannot share one, so callers diff them by
        ``(model, id)`` instead of by set arithmetic.
        """
        self.ensure_one()
        return [record for record in (self.partner_id,) if record]

    def _history_target_map(self):
        """``_history_targets`` keyed by ``(model, id)``.

        Targets can be of different models, so they cannot be diffed as
        recordsets; the key is what lets ``write`` tell an added link from a
        removed one.
        """
        self.ensure_one()
        return {(record._name, record.id): record
                for record in self._history_targets()}

    def write(self, vals):
        """Keep the mirrored history pointing at the linked records.

        The snapshot is taken before ``super`` and compared after, so the hook
        never needs to know which field changed or which models a bridge
        module added — only that the set of targets moved.
        """
        if not any(field in vals for field in self._history_link_fields()):
            return super().write(vals)
        before = {conv.id: conv._history_target_map() for conv in self}
        result = super().write(vals)
        history = self.env["omnichannel.history.service"]
        for conv in self:
            after = conv._history_target_map()
            gone = [record for key, record in before[conv.id].items()
                    if key not in after]
            added = [record for key, record in after.items()
                     if key not in before[conv.id]]
            if gone:
                history.purge(conv, gone)
            if added:
                history.backfill(conv, added)
        if "partner_id" in vals:
            self._propagate_partner_to_identity()
        return result

    def _propagate_partner_to_identity(self):
        """Point the external identity at the contact the operator just chose.

        Without it, the next inbound message from the same external account
        auto-creates yet another nameless contact and the operator re-links by
        hand forever. An identity that already has a contact is left alone:
        overwriting it would reroute every future conversation from that
        account on the strength of one operator's click here.
        """
        for conv in self:
            identity = conv.identity_id
            if not conv.partner_id or not identity or identity.partner_id:
                continue
            identity.sudo().partner_id = conv.partner_id
            conv.message_post(body=_(
                "Contact %(partner)s linked to this %(channel)s identity — "
                "future conversations from it land on the same contact.",
                partner=conv.partner_id.display_name,
                channel=conv.channel_id.name or _("channel")))

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
            chan = escape(conv.channel_id.name or code or "Channel")
            name = escape(
                conv.partner_id.display_name
                or conv.identity_id.display_name or conv.name or "Unknown")
            parts = [
                self._channel_badge(code, chan, 15),
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
            label = escape(conv.channel_id.name or code or "Channel")
            conv.channel_icon = self._channel_badge(code, label, 16)

    @api.model
    def _channel_badge(self, code, label, size):
        """Return the inline channel marker for ``code``, ``size`` px square.

        A FontAwesome glyph where one exists, the brand PNG otherwise: the
        bundled FontAwesome has no glyph for every channel we support, and a
        missing one fails silently as an empty cell rather than as a fallback
        shape. ``label`` must already be escaped.
        """
        if code in CHANNEL_IMAGE_ICONS:
            return Markup(
                '<img src="%s" alt="%s" title="%s" style="width:%dpx;'
                'height:%dpx;border-radius:2px;vertical-align:middle"/>') % (
                CHANNEL_AVATAR_URL % code, label, label, size, size)
        icon, color = CHANNEL_ICONS.get(code, CHANNEL_ICON_DEFAULT)
        return Markup(
            '<i class="fa %s" style="color:%s;line-height:1;font-size:%dpx" '
            'title="%s" role="img" aria-label="%s"></i>') % (
            icon, color, size, label, label)

    @api.model
    def _channel_avatar_b64(self, code):
        """Return the base64 brand avatar for a channel code, or False."""
        if code not in CHANNEL_AVATAR_CODES:
            return False
        try:
            with file_open((CHANNEL_AVATAR_URL % code).lstrip("/"), "rb") as fh:
                return base64.b64encode(fh.read())
        except (FileNotFoundError, OSError):
            return False

    def _ensure_discuss_channel(self):
        """Create the linked discuss.channel on first need."""
        self.ensure_one()
        if self.discuss_channel_id:
            return self.discuss_channel_id
        vals = {
            "name": self.name or _("Conversation"),
            "channel_type": "channel",
        }
        avatar = self._channel_avatar_b64(self.channel_id.code)
        if avatar:
            vals["image_128"] = avatar
        channel = self.env["discuss.channel"].create(vals)
        self.discuss_channel_id = channel
        channel.omni_conversation_id = self.id
        # Membership is added afterwards, through _sync_channel_members, so it
        # goes via discuss.channel.add_members like every other path.
        self._sync_channel_members()
        return channel

    def _sync_channel_members(self):
        """Ensure the assigned operator is a member of the mirror channel so
        Odoo's Discuss systray raises the native unread badge / notification
        on new inbound messages."""
        for conv in self:
            if not conv.operator_id:
                continue
            channel = conv._ensure_discuss_channel()
            partner = conv.operator_id.partner_id
            if not partner:
                continue
            # add_members, never a bare discuss.channel.member create: it is
            # what pushes "discuss.channel/joined" to the operator's own bus
            # channel, and that notification is what makes an already-open
            # browser subscribe to this channel's bus. A raw create writes a
            # correct membership row that the running session never hears
            # about — so no live message, no unread badge and no sound until
            # the operator reloads the page. add_members is idempotent: it
            # skips partners who are members already.
            # post_joined_message=False keeps the customer-facing mirror thread
            # free of "joined the channel" notices.
            channel.sudo().add_members(
                partner_ids=partner.ids, post_joined_message=False)
            member = channel.sudo().channel_member_ids.filtered(
                lambda m: m.partner_id == partner)
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

    def _ensure_operator(self):
        """Assign the current user as operator when the conversation is still
        unassigned and they act on it (e.g. send a reply), so replying doubles
        as taking it — no separate Take click needed. Never overrides an
        existing assignment (a colleague's conversation stays theirs)."""
        for conv in self:
            if conv.operator_id:
                continue
            conv.operator_id = self.env.user
            if conv.state == "new":
                conv.state = "open"
            conv._sync_channel_members()
            conv.message_post(
                body=_("Assigned to %s on reply.", self.env.user.name))
            conv._notify_omni_event("conversation_assigned")

    @api.model
    def _close_reason_policy(self):
        """Return the closing-reason policy: 'off', 'optional' or 'required'.

        Read from the parameter on every call rather than cached on the
        record, so flipping the setting takes effect for the next click and
        not the next registry reload. ``get_param`` falls back to the default
        for a missing *or* empty value, which is what makes an installation
        that never touched the setting behave exactly as before.
        """
        return self.env["ir.config_parameter"].sudo().get_param(
            CLOSE_REASON_POLICY_PARAM, "off")

    def action_set_pending(self):
        self.write({"state": "pending"})

    def action_close(self):
        """Close the conversations — asking why first when the setting
        says so.

        Returns the wizard action instead of closing when a reason is wanted.
        The state change then happens in the wizard's own call to ``_close``,
        which is what lets the 'required' policy refuse to close at all: the
        button never writes the Closed state itself.
        """
        if self._close_reason_policy() == "off":
            return self._close()
        return {
            "type": "ir.actions.act_window",
            "name": _("Close Conversation"),
            "res_model": "omnichannel.close.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_conversation_ids": [(6, 0, self.ids)]},
        }

    def _close(self, reason=None, note=None):
        """Close the conversations, recording why.

        The single door every close goes through — the header button, the
        close wizard, and anything automated later. Keeping the write in one
        place is what lets the 'required' policy refuse to close at all: the
        caller decides whether to open this door, and no code path in this
        suite writes the Closed state behind it. A direct ``write({"state":
        "closed"})`` over RPC still bypasses this method entirely — this is
        a workflow guard, not a database-level invariant.
        """
        self.write({
            "state": "closed",
            "closed_at": fields.Datetime.now(),
            "closed_by": self.env.uid,
            "close_reason_id": reason.id if reason else False,
            "close_note": note or False,
        })
        for conv in self:
            conv.message_post(body=conv._close_message(reason, note))
            conv._notify_omni_event("conversation_closed")
        return True

    def _close_message(self, reason, note):
        """Chatter body for a closure: who closed it, why, and their words."""
        self.ensure_one()
        if reason:
            line = _("Closed by %(user)s — %(reason)s",
                     user=self.env.user.name, reason=reason.name)
        else:
            line = _("Closed by %(user)s", user=self.env.user.name)
        if not note:
            return escape(line)
        return Markup("%s<br/>%s") % (line, note)

    def action_reopen(self):
        for conv in self:
            conv.message_post(body=conv._reopen_message())
        self.write({"state": "open", "closed_at": False, "closed_by": False,
                    "close_reason_id": False, "close_note": False})

    def _reopen_message(self):
        """Chatter body for a reopen: names the close reason about to be
        wiped, so it survives in the history even after the field is
        cleared (e.g. an inbound reply auto-reopening a closed thread)."""
        self.ensure_one()
        if self.close_reason_id:
            return _("Reopened — clearing the close reason (%s).",
                     self.close_reason_id.name)
        return _("Reopened.")

    def _notify_omni_event(self, event_name, payload=None):
        """Push a lightweight realtime signal so the Inbox thread and list
        refresh without a manual reload.

        It targets the assigned operator's own partner bus channel, which is
        always subscribed — unlike a mirror discuss.channel, whose client-side
        bus subscription only settles after a page reload when membership was
        just granted. Also a hook point for future automations/CRM/AI.
        """
        self.ensure_one()
        partner = self.operator_id.partner_id
        if not partner:
            return True
        data = {
            "event": event_name,
            "conversation_id": self.id,
            "channel_id": self.discuss_channel_id.id,
            "state": self.state,
        }
        if payload:
            data.update(payload)
        self.env["bus.bus"]._sendone(partner, "omni.inbox", data)
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
