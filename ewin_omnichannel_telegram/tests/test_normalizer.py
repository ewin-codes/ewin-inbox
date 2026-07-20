from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNormalizer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_telegram.channel_telegram")
        cls.account = cls.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": cls.channel.id})
        cls.norm = cls.env["omnichannel.telegram.normalizer"]

    def _update(self, **msg):
        base = {"update_id": 111, "message": {
            "message_id": 987, "date": 1700000000,
            "from": {"id": 123, "first_name": "Ivan", "last_name": "Petrov",
                     "username": "ivan", "language_code": "ru"},
            "chat": {"id": 123, "type": "private"}}}
        base["message"].update(msg)
        return base

    def test_text(self):
        ev = self.norm.normalize_update(self.account, self._update(text="Hi"))
        self.assertEqual(ev["message"]["type"], "text")
        self.assertEqual(ev["message"]["text"], "Hi")
        self.assertEqual(ev["external_user"]["name"], "Ivan Petrov")
        self.assertEqual(ev["event_id"], "telegram:update:111")

    def test_photo(self):
        ev = self.norm.normalize_update(self.account, self._update(
            photo=[{"file_id": "small"}, {"file_id": "big"}], caption="look"))
        self.assertEqual(ev["message"]["type"], "image")
        self.assertEqual(ev["message"]["attachments"][0]["file_id"], "big")

    def test_document(self):
        ev = self.norm.normalize_update(self.account, self._update(
            document={"file_id": "d1", "file_name": "cv.pdf",
                      "mime_type": "application/pdf"}))
        self.assertEqual(ev["message"]["type"], "document")
        self.assertEqual(ev["message"]["attachments"][0]["filename"], "cv.pdf")

    def test_no_username(self):
        upd = self._update(text="Hi")
        upd["message"]["from"].pop("username")
        ev = self.norm.normalize_update(self.account, upd)
        self.assertIsNone(ev["external_user"]["username"])

    def test_unknown_type(self):
        # a genuinely unhandled update kind (poll/dice/game) → unsupported
        ev = self.norm.normalize_update(self.account, self._update(
            poll={"id": "p1", "question": "?"}))
        self.assertEqual(ev["message"]["type"], "unsupported")

    def test_voice(self):
        ev = self.norm.normalize_update(self.account, self._update(
            voice={"file_id": "v1", "duration": 3}))
        att = ev["message"]["attachments"][0]
        self.assertEqual(ev["message"]["type"], "voice")
        self.assertEqual(att["filename"], "voice_v1.oga")
        self.assertEqual(att["mime_type"], "audio/ogg")

    def test_audio_uses_metadata_name(self):
        ev = self.norm.normalize_update(self.account, self._update(
            audio={"file_id": "a1", "performer": "Band", "title": "Song"}))
        att = ev["message"]["attachments"][0]
        self.assertEqual(ev["message"]["type"], "audio")
        self.assertEqual(att["filename"], "Band - Song.mp3")

    def test_video(self):
        ev = self.norm.normalize_update(self.account, self._update(
            video={"file_id": "vid1"}, caption="clip"))
        self.assertEqual(ev["message"]["type"], "video")
        self.assertEqual(ev["message"]["text"], "clip")
        self.assertEqual(ev["message"]["attachments"][0]["filename"], "video_vid1.mp4")

    def test_video_note(self):
        ev = self.norm.normalize_update(self.account, self._update(
            video_note={"file_id": "vn1"}))
        self.assertEqual(ev["message"]["type"], "video")
        self.assertEqual(ev["message"]["attachments"][0]["mime_type"], "video/mp4")

    def test_static_sticker_is_previewable_webp(self):
        ev = self.norm.normalize_update(self.account, self._update(
            sticker={"file_id": "s1", "emoji": "\U0001F600"}))
        att = ev["message"]["attachments"][0]
        self.assertEqual(ev["message"]["type"], "sticker")
        self.assertEqual(ev["message"]["text"], "\U0001F600")
        self.assertEqual(att["filename"], "sticker_s1.webp")
        self.assertEqual(att["mime_type"], "image/webp")

    def test_animated_sticker_not_previewable(self):
        ev = self.norm.normalize_update(self.account, self._update(
            sticker={"file_id": "s2", "is_animated": True, "emoji": "\U0001F525"}))
        att = ev["message"]["attachments"][0]
        self.assertEqual(att["filename"], "sticker_s2.tgs")
        self.assertIsNone(att["mime_type"])

    def test_location(self):
        ev = self.norm.normalize_update(self.account, self._update(
            location={"latitude": 55.75, "longitude": 37.61}))
        self.assertEqual(ev["message"]["type"], "location")
        self.assertIn("55.75", ev["message"]["text"])
        self.assertIn("openstreetmap.org", ev["message"]["text"])

    def test_contact(self):
        ev = self.norm.normalize_update(self.account, self._update(
            contact={"first_name": "Ivan", "phone_number": "+79001234567"}))
        self.assertEqual(ev["message"]["type"], "contact")
        self.assertIn("Ivan", ev["message"]["text"])
        self.assertIn("+79001234567", ev["message"]["text"])

    def test_non_message_update_ignored(self):
        self.assertIsNone(self.norm.normalize_update(
            self.account, {"update_id": 5, "edited_message": {}}))

    def test_document_filename_fallback(self):
        ev = self.norm.normalize_update(self.account, self._update(
            document={"file_id": "d2"}))
        self.assertEqual(ev["message"]["attachments"][0]["filename"], "file_d2")

    def test_reply_to_extraction(self):
        ev = self.norm.normalize_update(self.account, self._update(
            text="Hi", reply_to_message={"message_id": 555}))
        self.assertEqual(
            ev["message"]["reply_to_external_message_id"], "555")

        ev_no_reply = self.norm.normalize_update(self.account, self._update(text="Hi"))
        self.assertIsNone(ev_no_reply["message"]["reply_to_external_message_id"])
