from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAttachmentService(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_telegram.channel_telegram")
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": cls.channel.id,
            "tg_bot_token": "T", "tg_webhook_secret": "S"})
        cls.connector = cls.env["omnichannel.connector.telegram"]
        cls.service = cls.env["omnichannel.telegram.attachment.service"]

    def _photo_update(self, uid=321, mid=555, upd=999):
        return {"update_id": upd, "message": {
            "message_id": mid, "date": 1700000000,
            "from": {"id": uid, "first_name": "Ivan"},
            "chat": {"id": uid, "type": "private"},
            "photo": [{"file_id": "abc123", "width": 90, "height": 90}]}}

    def test_oversized_attachment_does_not_block_message_creation(self):
        # Critical A: a store() failure (oversize) must degrade gracefully -
        # the inbound message is still created, just without the attachment.
        # NOTE: tg_max_file_size=0 falls back to the 20MB default (`or 20`
        # in store()), so we set a real 1MB cap and feed it an oversized
        # payload to actually exceed it.
        self.account.tg_max_file_size = 1
        headers = {"X-Telegram-Bot-Api-Secret-Token": "S"}
        oversized = b"x" * (2 * 1024 * 1024)
        with patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.get_file",
                   return_value={"file_path": "x"}), \
             patch("odoo.addons.ewin_omnichannel_telegram.services."
                   "telegram_api_client.TelegramApiClient.download_file",
                   return_value=oversized):
            res = self.connector.parse_webhook(
                self.account, self._photo_update(), headers)
        self.assertTrue(res)
        msg = self.env["omnichannel.message"].search(
            [("account_id", "=", self.account.id)])
        self.assertEqual(len(msg), 1)
        self.assertEqual(msg.message_type, "image")
        self.assertFalse(msg.attachment_ids)
        log = self.env["omnichannel.error.log"].search([
            ("account_id", "=", self.account.id), ("category", "=", "attachment")])
        self.assertTrue(log)

    def test_reprocess_failed_event(self):
        # Critical B: an existing "failed" event must be reprocessed, not
        # treated as an already-handled duplicate.
        update_id = 4242
        external_event_id = f"telegram:update:{update_id}"
        self.env["omnichannel.event"].create({
            "account_id": self.account.id,
            "external_event_id": external_event_id,
            "event_type": "message",
            "state": "failed",
            "payload": {},
        })
        headers = {"X-Telegram-Bot-Api-Secret-Token": "S"}
        update = {"update_id": update_id, "message": {
            "message_id": 1, "date": 1700000000,
            "from": {"id": 7, "first_name": "Ivan"},
            "chat": {"id": 7, "type": "private"}, "text": "Retry me"}}
        res = self.connector.parse_webhook(self.account, update, headers)
        self.assertTrue(res)
        msg = self.env["omnichannel.message"].search(
            [("account_id", "=", self.account.id)])
        self.assertEqual(len(msg), 1)
        event = self.env["omnichannel.event"].search([
            ("account_id", "=", self.account.id),
            ("external_event_id", "=", external_event_id)])
        self.assertEqual(len(event), 1)
        self.assertEqual(event.state, "processed")

    def test_dangerous_mimetype_neutralized(self):
        # Important 1: attacker-controlled mimetype must never survive as-is
        # for browser-executable types, and blocked extensions get suffixed.
        # The payload bytes are opaque binary (not real HTML markup) so this
        # exercises our explicit mime_type-field check in isolation, without
        # tripping ir.attachment's own independent content-sniffing pass.
        att = self.service.store(
            self.account, b"\x00\x01\x02\xff\xfe\xfd\x10\x20\x30\x40",
            "page.html", "text/html")
        self.assertEqual(att.mimetype, "application/octet-stream")
        self.assertFalse(att.name.endswith(".html"))

    def test_html_content_sniffed_and_neutralized(self):
        # Defense-in-depth: even if the actual bytes are genuine HTML
        # markup (so ir.attachment's own content sniffing would otherwise
        # re-derive "text/html" from the raw content), the
        # attachments_mime_plainxml context forces it to a safe, non
        # browser-executable type.
        att = self.service.store(self.account, b"<html>x</html>", "page.html",
                                 "text/html")
        self.assertNotIn(att.mimetype, ("text/html", "application/xhtml+xml",
                                        "image/svg+xml"))

    def test_normal_image_mimetype_kept(self):
        att = self.service.store(self.account, b"\xff\xd8\xff", "pic.jpg",
                                 "image/jpeg")
        self.assertEqual(att.mimetype, "image/jpeg")
