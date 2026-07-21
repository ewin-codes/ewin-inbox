from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNormalizer(TransactionCase):
    def setUp(self):
        super().setUp()
        self.norm = self.env["omnichannel.instagram.normalizer"]
        self.channel = self.env.ref(
            "ewin_omnichannel_instagram.channel_instagram")
        self.account = self.env["omnichannel.account"].create({
            "name": "IG", "channel_id": self.channel.id, "ig_user_id": "IG1"})

    def _messaging(self, message):
        return {"sender": {"id": "USER1"}, "recipient": {"id": "IG1"},
                "timestamp": 1700000000000, "message": message}

    def test_text_message(self):
        m = self._messaging({"mid": "m_1", "text": "Hello"})
        ev = self.norm.normalize_messaging(self.account, m)
        self.assertEqual(ev["message"]["type"], "text")
        self.assertEqual(ev["message"]["text"], "Hello")
        self.assertEqual(ev["external_user"]["id"], "USER1")
        self.assertEqual(ev["conversation"]["external_id"], "USER1")
        self.assertEqual(ev["event_id"], "instagram:msg:m_1")

    def test_image_attachment_produces_file_spec(self):
        m = self._messaging({"mid": "m_2", "attachments": [{
            "type": "image",
            "payload": {"url": "https://cdn.example/a.jpg"}}]})
        ev = self.norm.normalize_messaging(self.account, m)
        self.assertEqual(ev["message"]["type"], "image")
        spec = ev["message"]["attachments"][0]
        self.assertEqual(spec["url"], "https://cdn.example/a.jpg")
        self.assertEqual(spec["type"], "image")

    def test_story_mention_stored_as_image(self):
        m = self._messaging({"mid": "m_sm", "attachments": [{
            "type": "story_mention",
            "payload": {"url": "https://cdn.example/story.jpg"}}]})
        ev = self.norm.normalize_messaging(self.account, m)
        self.assertEqual(ev["message"]["type"], "image")
        self.assertEqual(
            ev["message"]["attachments"][0]["url"],
            "https://cdn.example/story.jpg")

    def test_share_renders_link_no_file(self):
        m = self._messaging({"mid": "m_sh", "attachments": [{
            "type": "share",
            "payload": {"url": "https://instagram.com/p/abc"}}]})
        ev = self.norm.normalize_messaging(self.account, m)
        self.assertEqual(ev["message"]["type"], "text")
        self.assertIn("instagram.com/p/abc", ev["message"]["text"])
        self.assertEqual(ev["message"]["attachments"], [])

    def test_story_reply_prefixes_text(self):
        m = self._messaging({"mid": "m_sr", "text": "love it",
                             "reply_to": {"story": {
                                 "url": "https://cdn.example/s.jpg",
                                 "id": "story_1"}}})
        ev = self.norm.normalize_messaging(self.account, m)
        self.assertIn("love it", ev["message"]["text"])
        self.assertIn("story", ev["message"]["text"].lower())

    def test_missing_mid_returns_none(self):
        m = self._messaging({"text": "no id"})
        self.assertIsNone(self.norm.normalize_messaging(self.account, m))

    def test_postback_becomes_text(self):
        messaging = {"sender": {"id": "USER1"}, "recipient": {"id": "IG1"},
                     "timestamp": 1700000000000,
                     "postback": {"mid": "m_pb", "title": "Get Started",
                                  "payload": "GET_STARTED"}}
        ev = self.norm.normalize_postback(self.account, messaging)
        self.assertEqual(ev["message"]["type"], "text")
        self.assertEqual(ev["message"]["text"], "Get Started")
        self.assertEqual(ev["event_id"], "instagram:msg:m_pb")

    def test_iter_messaging_classifies_events(self):
        payload = {"object": "instagram", "entry": [{"messaging": [
            {"sender": {"id": "U"}, "message": {"mid": "m", "text": "x"}},
            {"sender": {"id": "U"}, "message": {"mid": "e", "is_echo": True}},
            {"sender": {"id": "U"}, "delivery": {"watermark": 1}},
            {"sender": {"id": "U"}, "read": {"watermark": 1}},
            {"sender": {"id": "U"}, "reaction": {"action": "react"}},
            {"sender": {"id": "U"}, "postback": {"payload": "P"}},
        ]}]}
        kinds = [k for k, _e, _m in self.norm.iter_messaging(payload)]
        self.assertEqual(
            kinds,
            ["message", "echo", "delivery", "read", "reaction", "postback"])
