from odoo import api, models


class LivechatNormalizer(models.AbstractModel):
    _name = "omnichannel.livechat.normalizer"
    _description = "Live Chat Message Normalizer"

    @api.model
    def event_id_for(self, mail_message):
        return f"livechat:message:{mail_message.id}"

    @api.model
    def is_visitor_message(self, channel, mail_message):
        """True when the post is a visitor comment we should ingest.

        Visitor-vs-operator uses the same signal website_livechat itself uses:
        a livechat post is the operator's iff its author is
        ``livechat_operator_id``. System notifications (message_type other
        than 'comment') are excluded too."""
        if channel.channel_type != "livechat":
            return False
        if mail_message.message_type != "comment":
            return False
        if mail_message.author_id and \
                mail_message.author_id == channel.livechat_operator_id:
            return False
        return True

    @api.model
    def _resolve_identity(self, channel, mail_message):
        visitor = channel.livechat_visitor_id
        if visitor and visitor.partner_id:
            partner = visitor.partner_id
            return {
                "id": f"partner:{partner.id}",
                "name": partner.name,
                "partner_id": partner.id,
                "language_code": partner.lang,
                "raw": {"visitor_id": visitor.id},
            }
        if visitor:
            return {
                "id": f"visitor:{visitor.id}",
                "name": channel.anonymous_name or f"Visitor #{visitor.id}",
                "language_code": visitor.lang_id.code,
                "raw": {"visitor_id": visitor.id},
            }
        guest_member = channel.channel_member_ids.filtered("guest_id")[:1]
        if guest_member:
            guest = guest_member.guest_id
            return {
                "id": f"guest:{guest.id}",
                "name": channel.anonymous_name or guest.name,
                "language_code": guest.lang,
                "raw": {"guest_id": guest.id},
            }
        return {
            "id": f"session:{channel.id}",
            "name": channel.anonymous_name or "Visitor",
            "raw": {},
        }

    @api.model
    def normalize_message(self, account, channel, mail_message):
        if not self.is_visitor_message(channel, mail_message):
            return None
        msg_type, text, attachments = self._extract_content(mail_message)
        return {
            "event_id": self.event_id_for(mail_message),
            "external_message_id": str(mail_message.id),
            "external_user": self._resolve_identity(channel, mail_message),
            "message": {
                "type": msg_type,
                "text": text,
                "attachments": attachments,
                "reply_to_external_message_id": None,
                "timestamp": mail_message.date,
                "raw": {"mail_message_id": mail_message.id,
                        "channel_id": channel.id},
            },
            "raw_payload": {"mail_message_id": mail_message.id,
                            "channel_id": channel.id},
        }

    @api.model
    def _extract_content(self, mail_message):
        specs = [{"attachment_id": a.id, "filename": a.name,
                  "mime_type": a.mimetype} for a in mail_message.attachment_ids]
        body = mail_message.body or ""
        if specs and not (mail_message.body or "").strip():
            first = mail_message.attachment_ids[0]
            mtype = "image" if (first.mimetype or "").startswith("image/") \
                else "document"
            return mtype, "", specs
        return "text", body, specs
