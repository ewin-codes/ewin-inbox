import hashlib
import re
from email.header import decode_header, make_header
from email.utils import parseaddr

from markupsafe import Markup, escape

from odoo import api, models

MSGID_RE = re.compile(r"<[^>]+>")


class EmailNormalizer(models.AbstractModel):
    _name = "omnichannel.email.normalizer"
    _description = "Email Message Normalizer"

    @api.model
    def normalize_message(self, account, msg):
        message_id = self._clean(msg.get("Message-ID"))
        if not message_id:
            basis = "%s|%s|%s" % (msg.get("From", ""), msg.get("Subject", ""),
                                  msg.get("Date", ""))
            message_id = "<%s@ewin-email>" % hashlib.sha1(
                basis.encode()).hexdigest()
        from_name, from_addr = parseaddr(self._decode(msg.get("From")) or "")
        from_addr = (from_addr or "").lower()
        subject = self._decode(msg.get("Subject")) or ""
        body, attachments = self._extract(msg)
        return {
            "event_id": f"email:{message_id}",
            "external_message_id": message_id,
            "thread_reference": self._thread_refs(msg),
            "external_user": {
                "id": from_addr,
                "name": from_name or None,
                "username": None, "phone": None, "language_code": None,
                "raw": {"from": from_addr, "subject": subject},
            },
            "conversation": {"external_id": from_addr, "type": "email"},
            "message": {
                "type": "text",
                "text": body,
                "subject": subject,
                "attachments": attachments,
                "reply_to_external_message_id": self._clean(
                    msg.get("In-Reply-To")),
                "timestamp": msg.get("Date"),
            },
            "raw_payload": {
                "message_id": message_id, "from": from_addr,
                "subject": subject, "date": msg.get("Date")},
        }

    @api.model
    def _thread_refs(self, msg):
        ids, seen = [], set()
        for header in ("In-Reply-To", "References"):
            value = msg.get(header)
            if not value:
                continue
            for mid in MSGID_RE.findall(value):
                if mid not in seen:
                    seen.add(mid)
                    ids.append(mid)
        return ids

    @api.model
    def _extract(self, msg):
        html = text = None
        attachments = []
        if msg.is_multipart():
            for part in msg.walk():
                if part.is_multipart():
                    continue
                cdisp = (part.get("Content-Disposition") or "").lower()
                ctype = part.get_content_type()
                filename = part.get_filename()
                if "attachment" in cdisp or filename:
                    attachments.append({
                        "filename": self._decode(filename) or "file",
                        "mime_type": ctype,
                        "data": part.get_payload(decode=True) or b"",
                    })
                elif ctype == "text/html" and html is None:
                    html = self._part_text(part)
                elif ctype == "text/plain" and text is None:
                    text = self._part_text(part)
        elif msg.get_content_type() == "text/html":
            html = self._part_text(msg)
        else:
            text = self._part_text(msg)
        if html:
            return html, attachments
        if text:
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            return escape(normalized).replace("\n", Markup("<br/>")), attachments
        return "", attachments

    @api.model
    def _part_text(self, part):
        data = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        try:
            return data.decode(charset, errors="replace")
        except LookupError:
            return data.decode("utf-8", errors="replace")

    @api.model
    def _decode(self, value):
        if not value:
            return value
        try:
            return str(make_header(decode_header(value)))
        except Exception:  # noqa: BLE001 - malformed header, keep raw
            return value

    @api.model
    def _clean(self, value):
        if not value:
            return value
        return value.strip().replace("\r", "").replace("\n", "")
