from markupsafe import Markup, escape

from odoo import api, fields, models

MESSAGE_TYPES = [
    ("text", "Text"), ("image", "Image"), ("document", "Document"),
    ("audio", "Audio"), ("video", "Video"), ("voice", "Voice"),
    ("location", "Location"), ("contact", "Contact"), ("sticker", "Sticker"),
    ("unsupported", "Unsupported"), ("system", "System"),
]

MESSAGE_STATES = [
    ("received", "Received"), ("queued", "Queued"), ("processing", "Processing"),
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

    def body_text(self):
        self.ensure_one()
        from odoo.tools import html2plaintext
        return html2plaintext(self.body or "") if self.body else ""
