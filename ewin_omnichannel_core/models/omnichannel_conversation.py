import base64

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import file_open, plaintext2html

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
CHANNEL_AVATAR_CODES = (
    "telegram", "viber", "email", "messenger", "whatsapp", "instagram",
    "livechat")
CHANNEL_AVATAR_URL = "/ewin_omnichannel_core/static/src/img/channel_%s.png"

# Channel codes drawn from that brand PNG in the lists too, because Odoo
# bundles FontAwesome 4.7 and it carries no glyph for Viber or Messenger — an
# <i class="fa fa-viber"> is a valid-looking tag that renders as a blank cell.
CHANNEL_IMAGE_ICONS = ("viber", "messenger")

# How hard the Close button asks why: "off" | "optional" | "required".
CLOSE_REASON_POLICY_PARAM = "ewin_omnichannel.close_reason_policy"

# Bus notification type the menu badges listen on. It carries no payload on
# purpose: it travels to every operator at once, and a conversation id in it
# would tell an operator about threads their own record rules keep out of
# their lists.
MENU_COUNTERS_BUS = "omni.menu.counters"

# The states in which a conversation is somebody's work. The Inbox list and
# both menu counts show these alone, and leaving them marks it read.
ACTIVE_STATES = ("new", "open")


class OmnichannelConversation(models.Model):
    _name = "omnichannel.conversation"
    _description = "Omnichannel Conversation"
    _inherit = ["mail.thread"]
    _order = "last_message_at desc, id desc"
    _check_company_auto = True

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
    identity_handle = fields.Char(
        related="identity_id.handle", string="Handle",
        help="Channel address of the customer (email, @username or phone), "
             "shown in the conversation header.")
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
        index=True, copy=False, ondelete="restrict", check_company=True,
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
    composer_scheduled_at = fields.Datetime(
        string="Send later", copy=False,
        help="Pick a moment to deliver this reply instead of sending it now.")
    composer_quote_edited = fields.Boolean(
        copy=False,
        help="The quote under the reply was changed in the composer; the "
             "edited copy below is what goes out.")
    composer_quote_body = fields.Html(
        copy=False, sanitize_style=True, string="Edited Quote")
    composer_editing_message_id = fields.Many2one(
        "omnichannel.message", string="Editing Scheduled Reply", copy=False,
        help="The waiting reply currently loaded into the composer, if any. "
             "Set while an operator edits one; cleared when they save or "
             "leave.")
    composer_signature = fields.Text(
        compute="_compute_composer_extras", string="Signature",
        help="What the channel signs a reply with, for the current user. The "
             "composer starts every reply with it, below the cursor.")
    composer_quote = fields.Html(
        compute="_compute_composer_extras", sanitize=False,
        string="Sent With the Reply",
        help="What the channel adds under the next reply by itself — for "
             "email, the conversation so far, quoted.")
    scheduled_count = fields.Integer(
        compute="_compute_scheduled", string="Scheduled Count")
    scheduled_badge = fields.Html(
        compute="_compute_scheduled", sanitize=False, string="Scheduled Badge",
        help="Clock badge for the list — empty when nothing is waiting, so the "
             "column stays quiet for the ordinary case.")

    @api.depends_context("uid")
    @api.depends("account_id", "omni_message_ids.state")
    def _compute_composer_extras(self):
        for conv in self:
            # A connector is an empty AbstractModel recordset — falsy — so it
            # is tested against None, never for truth.
            connector = conv.account_id and conv.account_id._get_connector(
                missing_ok=True)
            if not conv.account_id or connector is None:
                conv.composer_signature = False
                conv.composer_quote = False
                continue
            conv.composer_signature = connector.composer_signature(conv)
            conv.composer_quote = connector.composer_quote(conv)

    @api.depends_context("uid")
    @api.depends("discuss_channel_id.channel_member_ids.message_unread_counter")
    def _compute_unread_count(self):
        partner = self.env.user.partner_id
        for conv in self:
            member = conv.discuss_channel_id.channel_member_ids.filtered(
                lambda m: m.partner_id == partner)[:1]
            conv.unread_count = member.message_unread_counter if member else 0

    @api.depends("omni_message_ids.state")
    def _compute_scheduled(self):
        """Count the replies still waiting, in one query for the whole list.

        Grouping in SQL rather than filtering ``omni_message_ids`` keeps the
        Inbox list from loading every message of every conversation on it.
        """
        counts = {}
        if self.ids:
            counts = {
                conversation.id: count
                for conversation, count in self.env["omnichannel.message"]._read_group(
                    [("conversation_id", "in", self.ids),
                     ("state", "=", "scheduled")],
                    groupby=["conversation_id"], aggregates=["__count"])
            }
        title = escape(_("Replies waiting to be sent"))
        for conv in self:
            count = counts.get(conv.id, 0)
            conv.scheduled_count = count
            conv.scheduled_badge = (
                Markup(
                    '<span class="badge text-bg-warning" title="%s">'
                    '<i class="fa fa-clock-o me-1"></i>%s</span>') % (title, count)
                if count else False)

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

    def unlink(self):
        """Take the mirrored copies down with the conversation.

        The ledger that finds them lives on ``omnichannel.message``, which is
        cascade-deleted with the conversation, so this has to happen before
        ``super`` — afterwards nothing points at the copies and they sit on the
        customer's card forever. Archiving is deliberately not affected: an
        archived conversation is still part of the customer's history.
        """
        history = self.env["omnichannel.history.service"]
        for conv in self:
            targets = conv._history_targets()
            if targets:
                history.purge(conv, targets)
        return super().unlink()

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
            # Without it Odoo computes base.group_user (mail's
            # _compute_group_public_id), and its read rule admits anyone
            # holding that group — every employee, and through the same rule
            # portal and public users. The mirror carries the full customer
            # history and the internal notes, so it is restricted to the group
            # that is allowed to work in the inbox at all. Which conversations
            # an operator may *find* is still decided by
            # rule_conversation_operator_scope on this model.
            "group_public_id": self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id,
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
        self._mark_read_by(self.env.user.partner_id)

    def _mark_read_by(self, partners=None, sync=False):
        """Mark the mirror channels read up to their last message.

        For the given partners only, or for every member when ``partners`` is
        None — which is what setting a conversation aside does: a conversation
        that waits for the customer, or is closed, holds nothing anyone still
        has to read, and an unread number left on it would keep announcing
        work that is already done.

        ``sync`` tells the members' open web clients to adopt the new state at
        once; the reader of an open thread does not need it, everyone else
        does. Members already up to date are skipped, so nobody is pinged for
        a number that did not move.
        """
        moved = self.env["res.partner"]
        for conv in self:
            channel = conv.discuss_channel_id
            if not channel or not channel.message_ids:
                continue
            last_id = max(channel.message_ids.ids)
            # sudo: marking a colleague's membership is the point of the
            # "everyone" case, and the current user's own row is filtered
            # below in the other — the access check is the caller's write on
            # the conversation, not the member row.
            for member in channel.sudo().channel_member_ids:
                if partners is not None and member.partner_id not in partners:
                    continue
                if member.seen_message_id.id >= last_id:
                    continue
                member._mark_as_read(last_id, sync=sync)
                moved |= member.partner_id
        # Reading is what makes the "My Conversations" badge fall, and the
        # number is each reader's own — aim the refresh at them alone.
        for partner in moved:
            self._notify_menu_counters(partner)

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
        """Park the conversations until the customer answers.

        Refused on a closed one: the closure fields would stay behind on a
        conversation that no longer shows as closed. Re-open is the way back.

        Parking it is also reading it: the ball is in the customer's court, so
        nothing in it is left for anyone here. The customer's answer brings it
        back as unread — see ``_state_after_customer_message``.
        """
        if any(conv.state == "closed" for conv in self):
            raise UserError(_(
                "A closed conversation cannot wait for the customer. "
                "Re-open it first."))
        self.write({"state": "pending"})
        self._mark_read_by(sync=True)
        # Leaving new/open takes it off both menu counts, the unassigned one
        # included, which no personal ping above can reach.
        self._notify_menu_counters()

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

        Conversations already closed are left alone: closing again must not
        rewrite who closed them and why, nor post the closure twice.

        Closing marks the conversation read for everyone in its mirror, for
        the same reason waiting for the customer does (``action_set_pending``).
        """
        to_close = self.filtered(lambda conv: conv.state != "closed")
        to_close.write({
            "state": "closed",
            "closed_at": fields.Datetime.now(),
            "closed_by": self.env.uid,
            "close_reason_id": reason.id if reason else False,
            "close_note": note or False,
        })
        to_close._mark_read_by(sync=True)
        for conv in to_close:
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
            return escape(_("Reopened — clearing the close reason (%s).",
                            self.close_reason_id.name))
        return escape(_("Reopened."))

    def _notify_omni_event(self, event_name, payload=None):
        """Push a lightweight realtime signal so the Inbox thread and list
        refresh without a manual reload.

        It targets the assigned operator's own partner bus channel, which is
        always subscribed — unlike a mirror discuss.channel, whose client-side
        bus subscription only settles after a page reload when membership was
        just granted. Also a hook point for future automations/CRM/AI.
        """
        self.ensure_one()
        # The badges move on every one of these events, and on the unassigned
        # ones there is no operator below to carry the signal.
        self._notify_menu_counters()
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

    @api.model
    def _notify_menu_counters(self, partner=None):
        """Tell the web client that the menu badges are stale.

        Aimed at one partner it refreshes that person alone. Aimed at nobody
        it reaches the whole floor: ir.websocket subscribes every user to a
        bus channel per group they hold, so the unclaimed queue — which
        belongs to no one and therefore has no personal channel to carry it —
        needs no channel of its own.
        """
        target = partner or self.env.ref(
            "ewin_omnichannel_core.group_omni_operator",
            raise_if_not_found=False)
        if target:
            self.env["bus.bus"]._sendone(target, MENU_COUNTERS_BUS, {})
        return True

    @api.model
    def omni_menu_counters(self):
        """The two numbers the Inbox and My Conversations menus wear.

        Both count messages rather than conversations, and both are read with
        the caller's own rights — the record rules decide what an operator is
        allowed to be told about.

        Only conversations that are new or open count: one waiting for the
        customer or closed holds nothing to do until the customer writes again,
        and that message brings it back to one of those two states anyway.

        Unassigned is the whole inbound side of every such conversation nobody
        has taken — exactly what the Inbox list shows. There is no read state
        to subtract there: reading is a Discuss channel membership, and an
        unassigned conversation has no member, so nothing in it has been read
        by anyone. Taking it, parking it or closing it is what empties the
        number.
        """
        unassigned = self.env["omnichannel.message"].search_count([
            ("direction", "=", "inbound"),
            ("conversation_id.operator_id", "=", False),
            ("conversation_id.state", "in", ACTIVE_STATES),
        ])
        mine = sum(self.search([
            ("operator_id", "=", self.env.uid),
            ("state", "in", ACTIVE_STATES),
        ]).mapped("unread_count"))
        return {"unassigned": unassigned, "mine": mine}

    def _composer_html(self):
        """The composer's plain text as the HTML a message body holds.

        The textarea is plain text and a message body is HTML: handed over
        as it is, every line break is whitespace inside one paragraph and a
        multi-line reply arrives as a single line. ``plaintext2html`` keeps
        them — a line break per line, a paragraph per blank line.

        A composer holding nothing but the signature it opened with is
        empty: Send on an untouched composer must not mail the customer a
        signature.
        """
        self.ensure_one()
        text = (self.composer_body or "").strip()
        if not text or text == (self.composer_signature or "").strip():
            return ""
        return plaintext2html(text)

    def _composer_quote(self):
        """The quote the operator edited in the composer, or None when they
        left it alone and the channel is to build its own. An edited quote
        may be empty — that is the operator deleting it."""
        self.ensure_one()
        if not self.composer_quote_edited:
            return None
        return self.composer_quote_body or ""

    def _post_composer(self, scheduled_at=None):
        """Post the composed reply, clearing the composer after.

        Shared logic for immediate send and scheduling: read the composer,
        validate it has content, call the service, mark read, and reset the
        composer (except composer_is_internal which persists).

        When the composer holds a reply that is being edited, both buttons act
        on that row instead of writing a new one — see ``_apply_scheduled_edit``.
        """
        self.ensure_one()
        body = self._composer_html()
        attachments = self.composer_attachment_ids
        if not body and not attachments:
            return
        editing = self.composer_editing_message_id
        if editing:
            self._apply_scheduled_edit(editing, body, attachments, scheduled_at)
        else:
            self.env["omnichannel.message.service"].create_outbound(
                self, body, is_internal=self.composer_is_internal,
                attachments=attachments, scheduled_at=scheduled_at,
                quote=self._composer_quote())
        self._mark_read()
        self.write({
            "composer_body": False,
            "composer_scheduled_at": False,
            "composer_editing_message_id": False,
            "composer_attachment_ids": [(5, 0, 0)],
            "composer_quote_edited": False,
            "composer_quote_body": False,
        })

    def _apply_scheduled_edit(self, message, body, attachments, scheduled_at):
        """Write the composer back onto the reply it was loaded from.

        Send and Schedule keep their ordinary meanings: Schedule moves the
        send time, Send delivers the edited wording immediately. Either way it
        is the same row — editing a deferred reply must never leave a second
        copy of it behind.

        ``_check_reschedulable`` is what makes this safe. It takes the row lock
        and refuses a reply that has already left, so the cron cannot deliver
        the old wording in the window between the click that loaded the reply
        and this write. The operator's text stays in the composer when that
        happens: it is theirs to schedule again, not ours to discard.
        """
        self.ensure_one()
        message._check_reschedulable()
        quote = self._composer_quote()
        vals = {
            "body": body,
            "quote_edited": quote is not None,
            "quote_body": quote or False,
        }
        if attachments:
            # Append. The reply's own files were never in the composer, and
            # dropping them because they are absent from it would delete work
            # the operator never touched.
            vals["attachment_ids"] = [(4, attachment.id)
                                      for attachment in attachments]
        if scheduled_at:
            vals["scheduled_at"] = scheduled_at
        message.write(vals)
        if not scheduled_at:
            message.action_send_now()

    def action_edit_scheduled(self, message_id):
        """Load a waiting reply back into the composer for editing.

        Editing reuses the composer rather than an editor of its own: the
        operator changes a deferred reply with the same textarea, the same
        quick replies and the same send-later control they wrote it with.
        """
        self.ensure_one()
        message = self.env["omnichannel.message"].browse(int(message_id)).exists()
        if not message or message.conversation_id != self:
            raise UserError(
                _("That reply does not belong to this conversation."))
        # The same right rescheduling needs: whoever may change the send time
        # may change the words.
        message.check_access("write")
        if message.state != "scheduled":
            raise UserError(_(
                "This reply is no longer waiting (%(state)s) and can no "
                "longer be edited.",
                state=message._state_label(message.state)))
        self.write({
            "composer_body": message.body_text().strip(),
            "composer_scheduled_at": message.scheduled_at,
            "composer_quote_edited": message.quote_edited,
            "composer_quote_body": message.quote_body,
            # A scheduled reply is never an internal note (the service refuses
            # the combination), so loading one always leaves note mode.
            "composer_is_internal": False,
            "composer_editing_message_id": message.id,
        })
        return True

    def action_clear_schedule_time(self):
        """Drop the moment picked for this reply, turning Schedule back into
        Send. Nothing else in the composer is touched — changing one's mind
        about *when* is not changing one's mind about *what*."""
        self.ensure_one()
        self.composer_scheduled_at = False
        return True

    def action_cancel_edit(self):
        """Leave edit mode, dropping the loaded text with it.

        The reply itself is untouched — walking away from the editor is not
        cancelling the send.
        """
        self.ensure_one()
        self.write({
            "composer_body": False,
            "composer_scheduled_at": False,
            "composer_editing_message_id": False,
            "composer_quote_edited": False,
            "composer_quote_body": False,
        })
        return True

    def scheduled_replies(self):
        """The replies still waiting on this conversation, shaped for the pane.

        Read over RPC by the pane widget rather than through the form's
        one2many, because the pane has to refresh itself the moment the cron
        releases a reply — and a one2many can only be refreshed by reloading
        the whole record, which would throw away whatever is half-typed in the
        composer. Going through ``search`` also keeps the record rules in
        force: an operator sees here exactly what they may see anywhere else.
        """
        self.ensure_one()
        messages = self.env["omnichannel.message"].search(
            [("conversation_id", "=", self.id), ("state", "=", "scheduled")],
            order="scheduled_at, id")
        return [{
            "id": message.id,
            "body": message.body_text().strip(),
            "scheduled_at": fields.Datetime.to_string(message.scheduled_at),
            "author": message.scheduled_by.name or "",
            "author_id": message.scheduled_by.id,
            "attachment_count": len(message.attachment_ids),
        } for message in messages]

    def action_send_reply(self):
        self._post_composer()

    def action_schedule_reply(self):
        """Park the composed reply until ``composer_scheduled_at``.

        Deliberately a separate button rather than a mode on Send: the
        composer's keyboard shortcut sends, so deferring is always an explicit
        click and never something an operator does by reflex.
        """
        self.ensure_one()
        if not self.composer_scheduled_at:
            raise UserError(
                _("Pick a date and time to send this reply later."))
        self._post_composer(scheduled_at=self.composer_scheduled_at)
