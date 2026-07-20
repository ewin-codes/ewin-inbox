from markupsafe import Markup

from odoo import api, models


class TelegramNormalizer(models.AbstractModel):
    _name = "omnichannel.telegram.normalizer"
    _description = "Telegram Update Normalizer"

    @api.model
    def event_id_for(self, update):
        return f"telegram:update:{update.get('update_id')}"

    @api.model
    def normalize_update(self, account, update):
        message = update.get("message")
        if not message:
            return None
        sender = message.get("from", {})
        chat = message.get("chat", {})
        full_name = " ".join(
            p for p in [sender.get("first_name"), sender.get("last_name")] if p)
        msg_type, text, attachments = self._extract_content(message)
        return {
            "event_id": self.event_id_for(update),
            "external_message_id": str(message.get("message_id")),
            "external_user": {
                "id": str(sender.get("id")),
                "name": full_name or None,
                "username": sender.get("username"),
                "phone": (message.get("contact") or {}).get("phone_number"),
                "language_code": sender.get("language_code"),
                "raw": sender,
            },
            "conversation": {
                "external_id": str(chat.get("id")),
                "type": chat.get("type", "private"),
            },
            "message": {
                "type": msg_type,
                "text": text,
                "attachments": attachments,
                "reply_to_external_message_id": str(
                    message["reply_to_message"]["message_id"])
                    if message.get("reply_to_message") else None,
                "timestamp": message.get("date"),
            },
            "raw_payload": update,
        }

    @api.model
    def _extract_content(self, message):
        """Return (type, text, attachments[list of provider file specs]).

        Media (photo/document/voice/audio/video/video_note/sticker) is turned
        into a downloadable file spec; the embedded Discuss thread renders it
        natively (image, audio/video player, file card). Location/contact carry
        no file, so their content is rendered as readable text in the body."""
        if "text" in message:
            return "text", message["text"], []
        if "photo" in message:
            # largest photo size is the last element
            largest = message["photo"][-1]
            return "image", message.get("caption"), [{
                "file_id": largest["file_id"], "type": "image",
                "filename": f"photo_{largest['file_id']}.jpg"}]
        if "document" in message:
            doc = message["document"]
            return "document", message.get("caption"), [{
                "file_id": doc["file_id"], "type": "document",
                "filename": doc.get("file_name", f"file_{doc['file_id']}"),
                "mime_type": doc.get("mime_type")}]
        if "voice" in message:
            voice = message["voice"]
            return "voice", message.get("caption"), [{
                "file_id": voice["file_id"], "type": "voice",
                "filename": f"voice_{voice['file_id']}.oga",
                "mime_type": voice.get("mime_type") or "audio/ogg"}]
        if "audio" in message:
            audio = message["audio"]
            name = audio.get("file_name") or " - ".join(
                p for p in [audio.get("performer"), audio.get("title")] if p)
            name = name or f"audio_{audio['file_id']}"
            if "." not in name:
                name = f"{name}.mp3"
            return "audio", message.get("caption"), [{
                "file_id": audio["file_id"], "type": "audio",
                "filename": name,
                "mime_type": audio.get("mime_type") or "audio/mpeg"}]
        if "video" in message:
            video = message["video"]
            return "video", message.get("caption"), [{
                "file_id": video["file_id"], "type": "video",
                "filename": video.get("file_name", f"video_{video['file_id']}.mp4"),
                "mime_type": video.get("mime_type") or "video/mp4"}]
        if "video_note" in message:
            note = message["video_note"]
            return "video", None, [{
                "file_id": note["file_id"], "type": "video",
                "filename": f"videonote_{note['file_id']}.mp4",
                "mime_type": "video/mp4"}]
        if "sticker" in message:
            sticker = message["sticker"]
            # static stickers are .webp (previewable); animated (.tgs) and
            # video (.webm) stickers cannot preview in a browser, so keep the
            # emoji as the body and offer the raw file for download.
            is_static = not sticker.get("is_animated") and not sticker.get("is_video")
            if is_static:
                ext, mime = "webp", "image/webp"
            elif sticker.get("is_video"):
                ext, mime = "webm", "video/webm"
            else:
                ext, mime = "tgs", None
            return "sticker", sticker.get("emoji") or None, [{
                "file_id": sticker["file_id"], "type": "sticker",
                "filename": f"sticker_{sticker['file_id']}.{ext}",
                "mime_type": mime}]
        if "location" in message:
            loc = message["location"]
            return "location", self._format_location(
                loc.get("latitude"), loc.get("longitude")), []
        if "contact" in message:
            return "contact", self._format_contact(message["contact"]), []
        return "unsupported", None, []

    @api.model
    def _format_location(self, lat, lng):
        if lat is None or lng is None:
            return "\U0001F4CD Location"
        url = ("https://www.openstreetmap.org/"
               "?mlat=%s&mlon=%s#map=16/%s/%s") % (lat, lng, lat, lng)
        return Markup('\U0001F4CD <a href="%s" target="_blank">'
                      'Location: %s, %s</a>') % (url, lat, lng)

    @api.model
    def _format_contact(self, contact):
        name = " ".join(
            p for p in [contact.get("first_name"), contact.get("last_name")]
            if p) or "Contact"
        phone = contact.get("phone_number")
        if phone:
            return Markup("\U0001F464 %s — %s") % (name, phone)
        return Markup("\U0001F464 %s") % name
