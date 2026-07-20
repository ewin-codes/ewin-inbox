from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestViberNormalizer(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_viber.channel_viber")
        cls.account = cls.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": cls.channel.id})
        cls.norm = cls.env["omnichannel.viber.normalizer"]

    def _update(self, message, token=5000):
        return {
            "event": "message", "timestamp": 1457764197627,
            "message_token": token,
            "sender": {"id": "abc=", "name": "John", "language": "en"},
            "message": message,
        }

    def test_text(self):
        ev = self.norm.normalize_update(
            self.account, self._update({"type": "text", "text": "Hi"}))
        self.assertEqual(ev["message"]["type"], "text")
        self.assertEqual(ev["message"]["text"], "Hi")
        self.assertEqual(ev["external_user"]["id"], "abc=")
        self.assertEqual(ev["external_user"]["name"], "John")
        self.assertEqual(ev["conversation"]["external_id"], "abc=")
        self.assertEqual(ev["external_message_id"], "5000")

    def test_url_becomes_text(self):
        ev = self.norm.normalize_update(self.account, self._update(
            {"type": "url", "media": "https://ex.com/x"}))
        self.assertEqual(ev["message"]["type"], "text")
        self.assertEqual(ev["message"]["text"], "https://ex.com/x")

    def test_picture(self):
        ev = self.norm.normalize_update(self.account, self._update(
            {"type": "picture", "media": "https://ex.com/p.jpg", "text": "look"}))
        att = ev["message"]["attachments"][0]
        self.assertEqual(ev["message"]["type"], "image")
        self.assertEqual(ev["message"]["text"], "look")
        self.assertEqual(att["url"], "https://ex.com/p.jpg")
        self.assertEqual(att["filename"], "photo_5000.jpg")

    def test_video(self):
        ev = self.norm.normalize_update(self.account, self._update(
            {"type": "video", "media": "https://ex.com/v.mp4", "size": 9}))
        self.assertEqual(ev["message"]["type"], "video")
        self.assertEqual(ev["message"]["attachments"][0]["mime_type"], "video/mp4")

    def test_file_keeps_name(self):
        ev = self.norm.normalize_update(self.account, self._update(
            {"type": "file", "media": "https://ex.com/d", "file_name": "cv.pdf",
             "size": 10}))
        self.assertEqual(ev["message"]["type"], "document")
        self.assertEqual(ev["message"]["attachments"][0]["filename"], "cv.pdf")

    def test_contact(self):
        ev = self.norm.normalize_update(self.account, self._update(
            {"type": "contact",
             "contact": {"name": "Ann", "phone_number": "+79001112233"}}))
        self.assertEqual(ev["message"]["type"], "contact")
        self.assertIn("Ann", ev["message"]["text"])
        self.assertIn("+79001112233", ev["message"]["text"])

    def test_location(self):
        ev = self.norm.normalize_update(self.account, self._update(
            {"type": "location", "location": {"lat": 55.75, "lon": 37.61}}))
        self.assertEqual(ev["message"]["type"], "location")
        self.assertIn("55.75", ev["message"]["text"])
        self.assertIn("openstreetmap.org", ev["message"]["text"])

    def test_sticker(self):
        ev = self.norm.normalize_update(self.account, self._update(
            {"type": "sticker", "sticker_id": 40100}))
        self.assertEqual(ev["message"]["type"], "sticker")
        self.assertEqual(ev["message"]["text"], "[Sticker]")
        self.assertEqual(ev["message"]["attachments"], [])

    def test_unknown_message_type(self):
        ev = self.norm.normalize_update(self.account, self._update(
            {"type": "rich_media"}))
        self.assertEqual(ev["message"]["type"], "unsupported")

    def test_non_message_event_ignored(self):
        self.assertIsNone(self.norm.normalize_update(
            self.account, {"event": "conversation_started",
                           "user": {"id": "x"}}))
        self.assertIsNone(self.norm.normalize_update(
            self.account, {"event": "webhook"}))
