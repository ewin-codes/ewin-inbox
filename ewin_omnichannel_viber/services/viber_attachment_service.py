import os

from odoo import api, models

ALLOWED_MIME_PREFIXES = ("image/", "application/pdf", "application/",
                          "text/", "audio/", "video/")
BLOCKED_EXTENSIONS = (".exe", ".bat", ".cmd", ".sh", ".js", ".msi",
                      ".scr", ".com", ".pif", ".html", ".htm", ".svg",
                      ".xhtml")
DANGEROUS_MIMETYPES = ("text/html", "application/xhtml+xml", "image/svg+xml")


class ViberAttachmentService(models.AbstractModel):
    _name = "omnichannel.viber.attachment.service"
    _description = "Viber Attachment Service"

    @api.model
    def sanitize_filename(self, filename):
        filename = (filename or "").replace("\\", "/")
        name = os.path.basename(filename or "file")
        name = name.replace("\x00", "").strip()
        root, ext = os.path.splitext(name)
        if ext.lower() in BLOCKED_EXTENSIONS:
            name = f"{root}{ext}.bin"
        return name or "file"

    @api.model
    def store(self, account, file_bytes, filename, mimetype=None):
        max_bytes = (account.viber_max_file_size or 50) * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise ValueError("Attachment exceeds maximum allowed size.")
        safe_name = self.sanitize_filename(filename)
        safe_mimetype = mimetype or "application/octet-stream"
        if (safe_mimetype in DANGEROUS_MIMETYPES
                or not safe_mimetype.startswith(ALLOWED_MIME_PREFIXES)):
            safe_mimetype = "application/octet-stream"
        # attachments_mime_plainxml: defense-in-depth. ir.attachment's own
        # content sniffing can re-derive a browser-executable mimetype
        # (text/html, svg, xml, ...) straight from the file bytes even when we
        # pass a neutral value above. This context flag forces such re-derived
        # xml-like content to text/plain regardless of the caller's privileges.
        return self.env["ir.attachment"].with_context(
            attachments_mime_plainxml=True).create({
                "name": safe_name,
                "raw": file_bytes,
                "mimetype": safe_mimetype,
            })
