import logging
import threading

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

MESSAGE_TYPES = [
    ("text", "Text"), ("image", "Image"), ("document", "Document"),
    ("audio", "Audio"), ("video", "Video"), ("voice", "Voice"),
    ("location", "Location"), ("contact", "Contact"), ("sticker", "Sticker"),
    ("unsupported", "Unsupported"), ("system", "System"),
]

MESSAGE_STATES = [
    ("received", "Received"), ("scheduled", "Scheduled"),
    ("queued", "Queued"), ("processing", "Processing"),
    ("sent", "Sent"), ("delivered", "Delivered"), ("read", "Read"),
    ("failed", "Failed"), ("cancelled", "Cancelled"),
]


class OmnichannelMessage(models.Model):
    _name = "omnichannel.message"
    _description = "Omnichannel Message"
    _order = "id desc"

    conversation_id = fields.Many2one(
        "omnichannel.conversation", required=True, ondelete="cascade", index=True)
    account_id = fields.Many2one(
        related="conversation_id.account_id", store=True, index=True)
    channel_id = fields.Many2one(
        related="conversation_id.channel_id", store=True, index=True,
        string="Channel")
    company_id = fields.Many2one(
        related="conversation_id.company_id", store=True, index=True)
    direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound")],
        required=True, index=True)
    sender_type = fields.Selection(
        [("customer", "Customer"), ("operator", "Operator"),
         ("system", "System"), ("bot", "Bot")], required=True)
    is_internal = fields.Boolean(
        default=False, help="Internal note, not sent to the customer.")
    author_partner_id = fields.Many2one("res.partner")
    external_message_id = fields.Char(index=True)
    external_reply_to_id = fields.Char()
    reply_to_id = fields.Many2one("omnichannel.message")
    message_type = fields.Selection(MESSAGE_TYPES, default="text", required=True)
    body = fields.Html(sanitize=True, sanitize_attributes=True)
    state = fields.Selection(
        MESSAGE_STATES, default="received", required=True, index=True,
        copy=False,
        help="Not copied: a duplicated message starts life as 'received' "
             "rather than reproducing a state like 'scheduled', which would "
             "carry no scheduled_at and fail the constraint that pairs them.")
    mail_message_id = fields.Many2one("mail.message")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")
    history_message_ids = fields.Many2many(
        "mail.message", "omni_message_history_rel", "omni_message_id",
        "mail_message_id", string="History Copies", copy=False,
        help="Chatter copies of this message on the customer records this "
             "conversation is linked to. Tracked so unlinking a contact or a "
             "lead removes exactly the copies that link created.")
    attachment_preview = fields.Html(
        compute="_compute_attachment_preview", sanitize=False,
        help="Rendered thumbnails/chips for the message attachments.")
    has_attachments = fields.Boolean(compute="_compute_attachment_preview")
    sent_at = fields.Datetime()
    received_at = fields.Datetime()
    delivered_at = fields.Datetime()
    read_at = fields.Datetime()
    error_code = fields.Char()
    error_message = fields.Text()
    retry_count = fields.Integer(default=0)
    next_retry_at = fields.Datetime()
    scheduled_at = fields.Datetime(
        index=True, copy=False, string="Sends at",
        help="When an outbound reply an operator deferred is due. Kept after "
             "delivery: 'sent_at' says when it actually went out, this says "
             "when it was meant to.")
    scheduled_by = fields.Many2one(
        "res.users", readonly=True, copy=False, string="Scheduled by")
    raw_payload = fields.Json(
        groups="ewin_omnichannel_core.group_omni_admin", default=dict)

    def init(self):
        # composite index for history pagination (conversation_id, received_at)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS omnichannel_message_conv_received_idx
            ON omnichannel_message (conversation_id, received_at)
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS omnichannel_message_acct_extmsg_idx
            ON omnichannel_message (account_id, external_message_id)
        """)

    @api.depends("attachment_ids", "attachment_ids.mimetype", "attachment_ids.name")
    def _compute_attachment_preview(self):
        for message in self:
            parts = []
            for att in message.attachment_ids:
                name = escape(att.name or "file")
                mimetype = att.mimetype or ""
                if mimetype.startswith("image/"):
                    parts.append(Markup(
                        '<a href="/web/content/%s?download=true" target="_blank" '
                        'class="o_omni_thumb_link" title="%s">'
                        '<img src="/web/image/%s" class="o_omni_thumb" alt="%s"/>'
                        '</a>') % (att.id, name, att.id, name))
                else:
                    parts.append(Markup(
                        '<a href="/web/content/%s?download=true" '
                        'class="o_omni_file badge text-bg-light" title="%s">'
                        '<i class="fa fa-paperclip me-1"/>%s</a>') % (att.id, name, name))
            message.has_attachments = bool(parts)
            message.attachment_preview = (
                Markup('<div class="o_omni_atts">%s</div>') % Markup("").join(parts)
                if parts else False)

    @api.constrains("state", "scheduled_at")
    def _check_scheduled_has_time(self):
        for message in self:
            if message.state == "scheduled" and not message.scheduled_at:
                raise ValidationError(
                    _("A scheduled message must carry a send time."))

    @api.model_create_multi
    def create(self, vals_list):
        """Guard the send time at creation time, not just on reschedule.

        A scheduled message created with a past time would fire on the very
        next cron tick. A composer that feeds messages into this model needs
        no future-time check of its own — this layer handles it. So an
        operator who picks a send time, leaves the form open for twenty
        minutes, then presses Schedule gets a validation error, not a silent
        immediate send.
        """
        for vals in vals_list:
            if vals.get("scheduled_at"):
                self._check_send_time_is_future(vals["scheduled_at"])
        return super().create(vals_list)

    def write(self, vals):
        """Guard the send time of a deferred reply.

        Both rules live here rather than in the composer or the panel. The
        panel edits its rows inline and any client can write over RPC, so a
        rule enforced in a view is not enforced at all.

        Only a write that touches ``scheduled_at`` is inspected, which is what
        leaves the release path free: it moves the state to ``queued`` without
        touching the time. When the send time actually changes, post a
        chatter line naming both the old and new times for accountability —
        a write that sets it to the value it already had is not a reschedule
        and gets no line.
        """
        # Capture the old scheduled_at before the write, for the chatter post.
        # Iterate to handle multi-record writes (e.g. bulk reschedule).
        old_times = {}
        if "scheduled_at" in vals:
            self._check_reschedulable()
            self._check_send_time_is_future(vals["scheduled_at"])
            old_times = {message.id: message.scheduled_at for message in self}
        result = super().write(vals)
        # Post a chatter line for each reply whose send time actually moved.
        if old_times:
            service = self.env["omnichannel.message.service"]
            for message in self:
                old_time = old_times[message.id]
                if old_time == message.scheduled_at:
                    continue
                message.conversation_id.message_post(body=_(
                    "Reply rescheduled from %(old)s to %(new)s by %(user)s.",
                    old=service._format_scheduled(old_time),
                    new=service._format_scheduled(message.scheduled_at),
                    user=self.env.user.name))
        return result

    def _check_reschedulable(self):
        """Refuse to move the send time of a message that is no longer waiting.

        Lock the rows before checking state to avoid a race with the cron's
        release_scheduled. Without the lock, a concurrent release can complete
        between the ORM cache read and the UPDATE, leaving the reschedule to
        silently land on a message that already went out. The lock waits for the
        release to finish, then the state re-check sees the truth. ORDER BY id
        prevents deadlock when two concurrent bulk reschedules overlap.
        """
        if not self.ids:
            return
        # Flush first: a buffered ORM write to state, not yet sent to the
        # database, is invisible to this raw SELECT until it is. The odd order
        # would let the lock read a state this very transaction already
        # changed but has not yet told PostgreSQL about.
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT id, state FROM omnichannel_message "
            "WHERE id IN %s ORDER BY id FOR UPDATE",
            (tuple(self.ids),))
        for row_id, state in self.env.cr.fetchall():
            if state != "scheduled":
                raise UserError(_(
                    "This message is no longer scheduled (%(state)s) — its "
                    "send time can no longer be changed.",
                    state=self._state_label(state)))

    def _state_label(self, state):
        """The state's own translated label, for interpolation into a
        user-facing message.

        The field's ``Selection`` pairs are the English source strings; using
        them straight would splice untranslated English words into an
        otherwise translated sentence. ``_description_selection`` returns the
        pairs already translated for the current language, the same source
        the state widget itself reads from.
        """
        return dict(self._fields["state"]._description_selection(self.env)
                    ).get(state, state)

    @api.model
    def _check_send_time_is_future(self, when):
        """A send time in the past would fire on the very next cron tick, which
        is not scheduling — it is an immediate send with extra steps."""
        if not when:
            return
        if fields.Datetime.to_datetime(when) <= fields.Datetime.now():
            raise UserError(_("The scheduled send time must be in the future."))

    def unlink(self):
        """Take this message's chatter copies down with it.

        The ledger is the only thing that knows where the copies are, and it
        lives in a relation table keyed on this row — so deleting the message
        first leaves the customer's card holding a text nothing points at any
        more. Same invariant ``omnichannel.conversation.unlink`` protects, one
        message at a time.
        """
        self.history_message_ids.sudo().unlink()
        return super().unlink()

    def body_text(self):
        self.ensure_one()
        from odoo.tools import html2plaintext
        return html2plaintext(self.body or "") if self.body else ""

    def _history_date(self):
        """When this message happened, for a chatter copy.

        Inbound messages carry ``received_at`` and outbound ones ``sent_at``;
        an outbound message still queued has neither yet, and falls back to
        when the row was written.
        """
        self.ensure_one()
        return self.received_at or self.sent_at or self.create_date

    @api.model
    def _cron_send_scheduled(self, limit=100):
        """Release every scheduled message whose time has come.

        The batch ``SELECT`` fetches the candidate list without locks. For each
        message, a fresh lock is taken just before release:

            SELECT id FROM omnichannel_message
             WHERE id = %s AND state = 'scheduled' AND scheduled_at <= %s
               FOR UPDATE SKIP LOCKED

        The lock covers exactly the window in which one message is released. If
        the lock finds no row, the message was rescheduled out of range, already
        released, or is held by an overlapping run—skipped and tried next tick.
        The ``scheduled_at <= now`` re-check catches an operator who moved the
        time while the batch was draining. ``SKIP LOCKED`` keeps two overlapping
        cron runs off each other's rows.

        Task 3's compare-and-swap in ``release_scheduled`` owns double-send
        prevention. This lock guards against the reschedule race: the operator's
        write meets the guard in ``write`` and raises a clear "no longer
        scheduled" error instead of silently updating a message the cron is
        releasing.

        Ordered by ``scheduled_at`` so that a backlog after downtime drains
        oldest-first, and committed per message like the job queue: one failure
        must not roll back its peers.
        """
        now = fields.Datetime.now()
        self.env.cr.execute("""
            SELECT id FROM omnichannel_message
             WHERE state = 'scheduled' AND scheduled_at <= %s
             ORDER BY scheduled_at, id
             LIMIT %s
        """, (now, limit))
        candidate_ids = [row[0] for row in self.env.cr.fetchall()]
        service = self.env["omnichannel.message.service"]
        testing = getattr(threading.current_thread(), "testing", False)
        for message_id in candidate_ids:
            # Re-lock the message before releasing. If it was rescheduled or
            # released by another process, this returns no row and we skip it.
            self.env.cr.execute("""
                SELECT id FROM omnichannel_message
                 WHERE id = %s AND state = 'scheduled' AND scheduled_at <= %s
                   FOR UPDATE SKIP LOCKED
            """, (message_id, now))
            if not self.env.cr.fetchone():
                continue
            message = self.browse(message_id)
            try:
                # Use sudo() to bypass access checks: the scheduler acts as the
                # system, not as the operator. Company record rules would reject
                # a message belonging to another company with AccessError, which
                # would silently fail the send. The operator's own access check
                # happens when they compose the reply, not when the cron releases it.
                service.release_scheduled(message.sudo())
            except Exception as err:  # noqa: BLE001 - one bad message, not the batch
                _logger.exception(
                    "Could not release scheduled message %s", message.id)
                if not testing:
                    # Outside tests each message owns its transaction, so
                    # rolling back drops only this one — including whatever
                    # partial state the failed release left behind. Under the
                    # test runner everything shares one transaction, and a
                    # rollback would take the test's own fixtures with it.
                    self.env.cr.rollback()
                # The message stays scheduled and is retried every tick with
                # no bound; this log entry is the only trace of the failure
                # an operator can see between tries — the panel just shows a
                # row whose time has passed.
                self.env["omnichannel.error.log"].sudo().log(
                    "internal", _("Failed to release a scheduled message"),
                    account=message.account_id,
                    conversation_id=message.conversation_id.id,
                    message_id=message.id, technical=str(err))
                if not testing:
                    self.env.cr.commit()
                continue
            if not testing:
                self.env.cr.commit()

    def action_send_now(self):
        """Deliver a scheduled reply ahead of its time (panel button).

        The release may lose a race with the cron and find the message already
        sent. The action tolerates this gracefully: it does not raise, and it
        does not post an audit line crediting the operator for work the cron
        did. The operator sees the release happened (state changed) and learns
        not to click again.
        """
        service = self.env["omnichannel.message.service"]
        for message in self:
            if message.state != "scheduled":
                # Harmless by design: the cron may have released it a moment
                # before the click landed.
                continue
            when = service._format_scheduled(message.scheduled_at)
            released = service.release_scheduled(message)
            if released:
                # Post the audit line only if this release actually sent the
                # message; if the cron got there first, the post-send events
                # are already logged.
                message.conversation_id.message_post(body=_(
                    "Scheduled reply sent now by %(user)s, ahead of %(when)s.",
                    user=self.env.user.name, when=when))
        return True

    def action_cancel_schedule(self):
        """Drop a scheduled reply before it is sent.

        Cancelling writes a state instead of deleting the row: operators hold
        no unlink right on messages, and the record of a decision *not* to send
        is worth as much as the record of a send. The state transition is
        guarded at the database level to prevent a race with the cron's
        release_scheduled — cancelling a message that has already been sent
        will raise rather than silently overwrite the sent state.
        """
        service = self.env["omnichannel.message.service"]
        for message in self:
            # Access control at the door, same as release_scheduled: raw SQL
            # runs behind the ORM's back and a record rule cannot constrain
            # it, so the check has to happen here, before the UPDATE, not be
            # left to something downstream noticing by accident.
            message.check_access("write")
            # Flush first: invalidate_recordset below defaults to flush=True,
            # which would otherwise flush a still-pending ORM write to state
            # *after* this UPDATE has already run — overwriting the raw SQL's
            # own result in the wrong direction. Flushing here first means
            # there is nothing left dirty for that later call to flush.
            self.env.flush_all()
            # Attempt the transition atomically: lock the row, re-check the
            # state at lock time (not cache time), then update.
            self.env.cr.execute("""
                UPDATE omnichannel_message SET state = 'cancelled'
                 WHERE id = %s AND state = 'scheduled'
                RETURNING id
            """, (message.id,))
            if not self.env.cr.fetchone():
                # The row was not in scheduled state — read its actual state
                # for the error message. A plain SELECT is enough: this is
                # only building an error string, not a decision that needs a
                # row lock, and FOR UPDATE here would just block on whatever
                # transaction is holding the row for no benefit.
                self.env.cr.execute(
                    "SELECT state FROM omnichannel_message WHERE id = %s",
                    (message.id,))
                row = self.env.cr.fetchone()
                actual_state = row[0] if row else "unknown"
                raise UserError(_(
                    "Only a scheduled reply can be cancelled — this one is "
                    "already %(state)s.",
                    state=self._state_label(actual_state)))
            message.invalidate_recordset(["state"])
            # The UPDATE goes behind the ORM's back, so the dependency graph must
            # be notified by hand so dependent computed fields recompute.
            message.modified(["state"])
            message._release_composer_edit()
            message.conversation_id.message_post(body=_(
                "Scheduled reply for %(when)s cancelled by %(user)s.",
                when=service._format_scheduled(message.scheduled_at),
                user=self.env.user.name))
        return True

    def _release_composer_edit(self):
        """Take this reply out of any composer holding it open for editing.

        A reply can leave — cancelled here, released by the cron — while an
        operator has it loaded in their composer. Leaving the link behind
        leaves the composer announcing that it is editing something that no
        longer exists, and every later save failing on a reply nobody is
        thinking about any more. Only the link is dropped: the text stays in
        the composer, where Schedule will make a new reply out of it.

        sudo, because the composer may be a colleague's and the cron is not a
        user at all. Nothing of theirs is read or written but this one link.
        """
        editors = self.env["omnichannel.conversation"].sudo().search(
            [("composer_editing_message_id", "in", self.ids)])
        if editors:
            editors.write({"composer_editing_message_id": False})
