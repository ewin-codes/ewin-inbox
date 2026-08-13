from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

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
    state = fields.Selection(MESSAGE_STATES, default="received", required=True, index=True)
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
        touching the time.
        """
        if "scheduled_at" in vals:
            self._check_reschedulable()
            self._check_send_time_is_future(vals["scheduled_at"])
        return super().write(vals)

    def _check_reschedulable(self):
        """Refuse to move the send time of a message that is no longer waiting."""
        labels = dict(MESSAGE_STATES)
        for message in self:
            if message.state != "scheduled":
                raise UserError(_(
                    "This message is no longer scheduled (%(state)s) — its "
                    "send time can no longer be changed.",
                    state=labels.get(message.state, message.state)))

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
