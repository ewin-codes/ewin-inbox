from markupsafe import Markup

from odoo import api, models

# WhatsApp message type -> core MESSAGE_TYPES value.
_TYPE_MAP = {
    "text": "text", "image": "image", "document": "document",
    "audio": "audio", "video": "video", "sticker": "sticker",
    "location": "location", "contacts": "contact",
}
_MEDIA_TYPES = {"image", "document", "audio", "video", "sticker"}
_DEFAULT_EXT = {"image": "jpg", "document": "bin", "audio": "ogg",
                "video": "mp4", "sticker": "webp"}
_DEFAULT_MIME = {"image": "image/jpeg", "document": "application/octet-stream",
                 "audio": "audio/ogg", "video": "video/mp4",
                 "sticker": "image/webp"}


class WhatsAppNormalizer(models.AbstractModel):
    _name = "omnichannel.whatsapp.normalizer"
    _description = "WhatsApp Payload Normalizer"

    @api.model
    def event_id_for(self, message_id):
        return f"whatsapp:msg:{message_id}"

    @api.model
    def iter_changes(self, payload):
        """Yield (kind, value, item) for every message/status in the webhook.

        kind is 'message' or 'status'. value is the change 'value' dict
        (carries contacts/metadata); item is the individual message/status."""
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {}) or {}
                for message in value.get("messages", []) or []:
                    yield "message", value, message
                for status in value.get("statuses", []) or []:
                    yield "status", value, status

    @api.model
    def normalize_message(self, account, value, message, contacts):
        wa_id = message.get("from")
        profile_name = None
        for contact in contacts or []:
            if contact.get("wa_id") == wa_id:
                profile_name = (contact.get("profile") or {}).get("name")
                break
        msg_type, text, attachments = self._extract_content(message)
        context = message.get("context") or {}
        return {
            "event_id": self.event_id_for(message.get("id")),
            "external_message_id": message.get("id"),
            "external_user": {
                "id": wa_id,
                "name": profile_name,
                "username": None,
                "phone": wa_id,
                "raw": {"wa_id": wa_id, "profile_name": profile_name},
            },
            "conversation": {"external_id": wa_id, "type": "private"},
            "message": {
                "type": msg_type,
                "text": text,
                "attachments": attachments,
                "reply_to_external_message_id": context.get("id"),
                "timestamp": self._as_int(message.get("timestamp")),
            },
            "raw_payload": message,
        }

    @api.model
    def _extract_content(self, message):
        wa_type = message.get("type")
        if wa_type == "text":
            return "text", (message.get("text") or {}).get("body"), []
        if wa_type in _MEDIA_TYPES:
            return self._extract_media(wa_type, message)
        if wa_type == "location":
            loc = message.get("location") or {}
            return "location", self._format_location(
                loc.get("latitude"), loc.get("longitude"), loc.get("name")), []
        if wa_type == "contacts":
            return "contact", self._format_contacts(
                message.get("contacts") or []), []
        if wa_type == "reaction":
            reaction = message.get("reaction") or {}
            emoji = reaction.get("emoji") or ""
            return "text", Markup("%s") % (emoji or "⭐"), []
        if wa_type == "button":
            return "text", (message.get("button") or {}).get("text"), []
        if wa_type == "interactive":
            return "text", self._format_interactive(
                message.get("interactive") or {}), []
        return "unsupported", None, []

    @api.model
    def _extract_media(self, wa_type, message):
        media = message.get(wa_type) or {}
        core_type = _TYPE_MAP[wa_type]
        mime = media.get("mime_type") or _DEFAULT_MIME[wa_type]
        # WhatsApp voice notes arrive as type=audio with voice=true.
        if wa_type == "audio" and media.get("voice"):
            core_type = "voice"
        ext = _DEFAULT_EXT[wa_type]
        base_mime = mime.split(";")[0]
        filename = media.get("filename") or f"{wa_type}_{media.get('id')}.{ext}"
        caption = media.get("caption")
        return core_type, caption, [{
            "media_id": media.get("id"),
            "type": core_type,
            "filename": filename,
            "mime_type": base_mime,
        }]

    @api.model
    def _format_location(self, lat, lng, name=None):
        if lat is None or lng is None:
            return "\U0001F4CD Location"
        url = ("https://www.openstreetmap.org/"
               "?mlat=%s&mlon=%s#map=16/%s/%s") % (lat, lng, lat, lng)
        label = name or ("%s, %s" % (lat, lng))
        return Markup('\U0001F4CD <a href="%s" target="_blank">%s</a>') % (
            url, label)

    @api.model
    def _format_contacts(self, contacts):
        parts = []
        for contact in contacts:
            name = ((contact.get("name") or {}).get("formatted_name")
                    or "Contact")
            phones = [p.get("phone") for p in contact.get("phones") or []
                      if p.get("phone")]
            phone = phones[0] if phones else ""
            parts.append("%s — %s" % (name, phone) if phone else name)
        return Markup("\U0001F464 %s") % "; ".join(parts) if parts \
            else Markup("\U0001F464 Contact")

    @api.model
    def _format_interactive(self, interactive):
        itype = interactive.get("type")
        if itype == "button_reply":
            return (interactive.get("button_reply") or {}).get("title")
        if itype == "list_reply":
            return (interactive.get("list_reply") or {}).get("title")
        return None

    @api.model
    def _as_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
