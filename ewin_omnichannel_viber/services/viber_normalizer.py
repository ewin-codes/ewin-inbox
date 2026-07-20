from markupsafe import Markup

from odoo import api, models


class ViberNormalizer(models.AbstractModel):
    _name = "omnichannel.viber.normalizer"
    _description = "Viber Update Normalizer"

    @api.model
    def event_id_for(self, update):
        # message_token is unique per message and repeated on Viber retries,
        # so it doubles as the idempotency key.
        return f"viber:msg:{update.get('message_token')}"

    @api.model
    def normalize_update(self, account, update):
        # Only "message" events carry customer content. Everything else
        # (subscribed / conversation_started / delivered / seen / webhook
        # validation) is acknowledged but not turned into a conversation.
        if update.get("event") != "message":
            return None
        sender = update.get("sender", {})
        message = update.get("message", {})
        token = update.get("message_token")
        msg_type, text, attachments = self._extract_content(message, token)
        return {
            "event_id": self.event_id_for(update),
            "external_message_id": str(token),
            "external_user": {
                "id": str(sender.get("id")),
                "name": sender.get("name") or None,
                "username": None,  # Viber has no @username concept
                "phone": (message.get("contact") or {}).get("phone_number"),
                "language_code": sender.get("language"),
                "raw": sender,
            },
            "conversation": {
                "external_id": str(sender.get("id")),
                "type": "private",
            },
            "message": {
                "type": msg_type,
                "text": text,
                "attachments": attachments,
                "reply_to_external_message_id": None,
                "timestamp": update.get("timestamp"),
            },
            "raw_payload": update,
        }

    @api.model
    def _extract_content(self, message, token):
        """Return (type, text, attachments[list of provider file specs]).

        Viber delivers media as a temporary public ``media`` URL (not a file
        id), so each spec carries a ``url`` the connector downloads directly."""
        mtype = message.get("type")
        if mtype == "text":
            return "text", message.get("text"), []
        if mtype == "url":
            # a shared link — keep the URL as the body text
            return "text", message.get("media"), []
        if mtype == "picture":
            return "image", message.get("text"), [{
                "url": message["media"], "type": "image",
                "filename": f"photo_{token}.jpg", "mime_type": "image/jpeg"}]
        if mtype == "video":
            return "video", message.get("text"), [{
                "url": message["media"], "type": "video",
                "filename": f"video_{token}.mp4", "mime_type": "video/mp4"}]
        if mtype == "file":
            return "document", None, [{
                "url": message["media"], "type": "document",
                "filename": message.get("file_name", f"file_{token}"),
                "mime_type": None}]
        if mtype == "contact":
            return "contact", self._format_contact(
                message.get("contact") or {}), []
        if mtype == "location":
            loc = message.get("location") or {}
            return "location", self._format_location(
                loc.get("lat"), loc.get("lon")), []
        if mtype == "sticker":
            # Viber stickers are referenced by numeric id with no downloadable
            # media URL, so show a marker rather than a broken attachment.
            return "sticker", "[Sticker]", []
        return "unsupported", None, []

    @api.model
    def _format_location(self, lat, lon):
        if lat is None or lon is None:
            return "\U0001F4CD Location"
        url = ("https://www.openstreetmap.org/"
               "?mlat=%s&mlon=%s#map=16/%s/%s") % (lat, lon, lat, lon)
        return Markup('\U0001F4CD <a href="%s" target="_blank">'
                      'Location: %s, %s</a>') % (url, lat, lon)

    @api.model
    def _format_contact(self, contact):
        name = contact.get("name") or "Contact"
        phone = contact.get("phone_number")
        if phone:
            return Markup("\U0001F464 %s — %s") % (name, phone)
        return Markup("\U0001F464 %s") % name
