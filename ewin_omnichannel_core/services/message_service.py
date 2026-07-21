from markupsafe import Markup

from odoo import api, fields, models

INTERNAL_BADGE = Markup(
    '<span class="o_omni_internal_marker">'
    '<i class="fa fa-lock"></i> Internal note</span>')


class MessageService(models.AbstractModel):
    _name = "omnichannel.message.service"
    _description = "Omnichannel Message Service"

    @api.model
    def create_inbound(self, conversation, normalized_message, attachments=None):
        ext_id = normalized_message.get("external_message_id")
        if ext_id:
            existing = self.env["omnichannel.message"].search([
                ("account_id", "=", conversation.account_id.id),
                ("external_message_id", "=", ext_id),
                ("direction", "=", "inbound"),
            ], limit=1)
            if existing:
                return existing
        now = fields.Datetime.now()
        msg_type = normalized_message.get("type", "text")
        supported = {"text", "image", "document", "audio", "video", "voice",
                     "location", "contact", "sticker"}
        if msg_type not in supported and msg_type != "system":
            msg_type = "unsupported"
        body = normalized_message.get("text") or ""
        if msg_type == "unsupported":
            body = body or "[Unsupported message type — open the source channel to view.]"
        message = self.env["omnichannel.message"].create({
            "conversation_id": conversation.id,
            "direction": "inbound",
            "sender_type": "customer",
            "message_type": msg_type,
            "body": body,
            "external_message_id": normalized_message.get("external_message_id"),
            "external_reply_to_id": normalized_message.get("reply_to_external_message_id"),
            "state": "received",
            "received_at": now,
            "author_partner_id": conversation.partner_id.id or False,
            "attachment_ids": [(6, 0, (attachments or self.env["ir.attachment"]).ids)],
            "raw_payload": normalized_message.get("raw", {}),
        })
        conv_vals = {
            "last_message_at": now,
            "last_customer_message_at": now,
            "state": "open" if conversation.state == "new" and conversation.operator_id
                     else conversation.state,
        }
        if not conversation.first_customer_message_at:
            conv_vals["first_customer_message_at"] = now
        conversation.write(conv_vals)
        self._mirror_to_discuss(conversation, message)
        # keep the assigned operator subscribed to the mirror channel so the
        # Discuss systray notifies them of this inbound even when the record
        # is not open (membership may predate their assignment).
        conversation._sync_channel_members()
        conversation._notify_omni_event("message_received")
        return message

    @api.model
    def _mirror_to_discuss(self, conversation, message):
        channel = conversation._ensure_discuss_channel()
        author = message.author_partner_id or conversation.partner_id \
            or self.env.ref("base.partner_root")
        # Internal notes stay in Odoo; prefix a visible badge so they are
        # obvious in the mirrored Discuss thread (they are not sent to the
        # customer). See discuss.channel override which skips forwarding them.
        body = Markup(message.body or "")
        if message.is_internal:
            body = INTERNAL_BADGE + body
        # omni_mirror flags this as our own mirror so the discuss.channel
        # override does not treat it as an operator reply to forward.
        mail_message = channel.with_context(omni_mirror=True).message_post(
            body=body,
            author_id=author.id,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            attachment_ids=message.attachment_ids.ids,
        )
        message.mail_message_id = mail_message.id
        return mail_message

    @api.model
    def create_outbound(self, conversation, body, is_internal=False, attachments=None):
        now = fields.Datetime.now()
        # Replying to a customer takes an unassigned conversation automatically
        # (internal notes do not — writing a note is not answering the customer).
        if not is_internal:
            conversation._ensure_operator()
        message = self.env["omnichannel.message"].create({
            "conversation_id": conversation.id,
            "direction": "outbound",
            "sender_type": "operator",
            "is_internal": is_internal,
            "message_type": "text",
            "body": body,
            "author_partner_id": self.env.user.partner_id.id,
            "state": "queued" if not is_internal else "sent",
            "attachment_ids": [(6, 0, (attachments or self.env["ir.attachment"]).ids)],
        })
        conv_vals = {
            "last_message_at": now,
            "last_operator_message_at": now,
        }
        if not is_internal and not conversation.first_operator_message_at:
            conv_vals["first_operator_message_at"] = now
        conversation.write(conv_vals)
        self._mirror_to_discuss(conversation, message)
        if not is_internal:
            # The first attempt is immediate (synchronous). Only retries go
            # through the ir.cron queue.
            self.env["omnichannel.routing.service"].deliver_outbound(message)
        return message

    @api.model
    def create_outbound_from_discuss(self, conversation, mail_message):
        """An operator typed directly in the linked Discuss channel. Wrap
        the existing mail.message as an outbound omni message and deliver it to
        the provider — without re-mirroring, since it is already in the channel.
        Idempotent on mail_message_id."""
        existing = self.env["omnichannel.message"].search(
            [("mail_message_id", "=", mail_message.id)], limit=1)
        if existing:
            return existing
        now = fields.Datetime.now()
        # An operator answering from the mirrored Discuss channel also takes
        # the conversation if it is still unassigned.
        conversation._ensure_operator()
        message = self.env["omnichannel.message"].create({
            "conversation_id": conversation.id,
            "direction": "outbound",
            "sender_type": "operator",
            "is_internal": False,
            "message_type": "text",
            "body": mail_message.body,
            "author_partner_id": mail_message.author_id.id,
            "mail_message_id": mail_message.id,
            "state": "queued",
            "attachment_ids": [(6, 0, mail_message.attachment_ids.ids)],
        })
        conv_vals = {
            "last_message_at": now,
            "last_operator_message_at": now,
        }
        if not conversation.first_operator_message_at:
            conv_vals["first_operator_message_at"] = now
        conversation.write(conv_vals)
        self.env["omnichannel.routing.service"].deliver_outbound(message)
        return message
