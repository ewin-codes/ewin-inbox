from markupsafe import Markup

from odoo import api, models

# Instagram attachment type -> core MESSAGE_TYPES value. A "story_mention" is
# the story media the customer tagged the business in, so it is stored like an
# image; "share" (a shared post/reel) has no downloadable media, so it renders
# as a link instead.
_ATTACH_MAP = {"image": "image", "audio": "audio", "video": "video",
               "file": "document", "story_mention": "image"}
_DEFAULT_EXT = {"image": "jpg", "audio": "mp3", "video": "mp4",
                "document": "bin", "sticker": "png"}
_DEFAULT_MIME = {"image": "image/jpeg", "audio": "audio/mpeg",
                 "video": "video/mp4", "document": "application/octet-stream",
                 "sticker": "image/png"}


class InstagramNormalizer(models.AbstractModel):
    """Maps Instagram's ``entry[].messaging[]`` webhook shape into Inbox's
    universal normalized event format (the same dict every connector feeds to
    the routing service)."""

    _name = "omnichannel.instagram.normalizer"
    _description = "Instagram Payload Normalizer"

    @api.model
    def event_id_for(self, mid):
        return f"instagram:msg:{mid}"

    @api.model
    def iter_messaging(self, payload):
        """Yield ``(kind, entry, messaging)`` for every event in the webhook.

        ``kind`` is one of message / echo / postback / delivery / read /
        reaction / other. A single POST can batch many events across accounts.
        """
        for entry in payload.get("entry", []) or []:
            for messaging in entry.get("messaging", []) or []:
                yield self._classify(messaging), entry, messaging

    @api.model
    def _classify(self, messaging):
        if "message" in messaging:
            if (messaging.get("message") or {}).get("is_echo"):
                return "echo"
            return "message"
        for key in ("postback", "delivery", "read", "reaction"):
            if key in messaging:
                return key
        return "other"

    @api.model
    def normalize_messaging(self, account, messaging):
        """Normalize an inbound user message. Returns None if it carries no
        message id (nothing we can dedupe or reference)."""
        message = messaging.get("message") or {}
        mid = message.get("mid")
        if not mid:
            return None
        igsid = (messaging.get("sender") or {}).get("id")
        msg_type, text, attachments = self._extract_content(message)
        reply_to = (message.get("reply_to") or {}).get("mid")
        return {
            "event_id": self.event_id_for(mid),
            "external_message_id": mid,
            "external_user": self._external_user(igsid),
            "conversation": {"external_id": igsid, "type": "private"},
            "message": {
                "type": msg_type,
                "text": text,
                "attachments": attachments,
                "reply_to_external_message_id": reply_to,
                "timestamp": self._as_int(messaging.get("timestamp")),
            },
            "raw_payload": messaging,
        }

    @api.model
    def normalize_postback(self, account, messaging):
        """Normalize a postback (icebreaker / button / generic reply) into a
        plain-text inbound message carrying its title or payload."""
        igsid = (messaging.get("sender") or {}).get("id")
        postback = messaging.get("postback") or {}
        mid = postback.get("mid")
        text = postback.get("title") or postback.get("payload") or ""
        event_id = (self.event_id_for(mid) if mid
                    else f"instagram:pb:{igsid}:{messaging.get('timestamp')}")
        return {
            "event_id": event_id,
            "external_message_id": mid,
            "external_user": self._external_user(igsid),
            "conversation": {"external_id": igsid, "type": "private"},
            "message": {
                "type": "text",
                "text": text,
                "attachments": [],
                "reply_to_external_message_id": None,
                "timestamp": self._as_int(messaging.get("timestamp")),
            },
            "raw_payload": messaging,
        }

    @api.model
    def _external_user(self, igsid):
        # The webhook only carries the Instagram-scoped id (IGSID); the display
        # name and @username are fetched separately via the Graph profile API
        # by the connector.
        return {"id": igsid, "name": None, "username": None, "phone": None,
                "raw": {"igsid": igsid}}

    @api.model
    def _extract_content(self, message):
        text = message.get("text")
        prefix = self._story_reply_prefix(message)
        attachments = message.get("attachments") or []
        if not attachments:
            return "text", self._join(prefix, text) or "", []
        specs = []
        rendered = [prefix] if prefix else []
        core_type = None
        for att in attachments:
            atype = att.get("type")
            payload = att.get("payload") or {}
            if atype in _ATTACH_MAP:
                url = payload.get("url")
                if not url:
                    continue
                spec = self._media_spec(atype, payload, message.get("mid"))
                core_type = core_type or spec["type"]
                specs.append(spec)
            elif atype in ("share", "ig_reel"):
                rendered.append(self._format_share(payload))
            elif atype == "location":
                coords = payload.get("coordinates") or {}
                rendered.append(self._format_location(
                    coords.get("lat"), coords.get("long"),
                    payload.get("title")))
                core_type = core_type or "location"
            elif atype == "fallback":
                rendered.append(self._format_fallback(payload))
            else:  # a template or attachment type we do not model yet
                core_type = core_type or "unsupported"
        if specs:
            caption = self._join(prefix, text)
            return core_type or "document", caption or None, specs
        if rendered:
            joined = Markup("<br/>").join(r for r in rendered if r)
            return (core_type if core_type == "location" else "text"), joined, []
        return "unsupported", self._join(prefix, text) or None, []

    @api.model
    def _story_reply_prefix(self, message):
        """A reply to one of the business's stories carries ``reply_to.story``
        (media URL + id) instead of a message ``mid``. Surface it as a small
        marker so the operator sees the reply is about their story."""
        story = (message.get("reply_to") or {}).get("story") or {}
        url = story.get("url")
        if not url:
            return None
        return Markup(
            '\U0001F4F8 <a href="%s" target="_blank">Replied to your story</a>'
        ) % url

    @api.model
    def _join(self, prefix, text):
        parts = [p for p in (prefix, text) if p]
        if not parts:
            return None
        if any(isinstance(p, Markup) for p in parts):
            return Markup("<br/>").join(Markup.escape(p) for p in parts)
        return "\n".join(parts)

    @api.model
    def _media_spec(self, atype, payload, mid):
        core_type = _ATTACH_MAP[atype]
        if atype == "image" and payload.get("sticker_id"):
            core_type = "sticker"
        ext = _DEFAULT_EXT[core_type]
        return {
            "url": payload.get("url"),
            "type": core_type,
            "filename": f"{atype}_{mid or 'file'}.{ext}",
            "mime_type": _DEFAULT_MIME[core_type],
        }

    @api.model
    def _format_share(self, payload):
        url = payload.get("url")
        title = payload.get("title")
        if url:
            return Markup(
                '\U0001F4CE <a href="%s" target="_blank">%s</a>') % (
                url, title or "Shared post")
        return Markup("\U0001F4CE %s") % (title or "Shared post")

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
    def _format_fallback(self, payload):
        title = payload.get("title")
        url = payload.get("url")
        if url:
            return Markup('\U0001F517 <a href="%s" target="_blank">%s</a>') % (
                url, title or url)
        return Markup("\U0001F517 %s") % (title or "Shared content")

    @api.model
    def _as_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
