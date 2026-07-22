from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNormalizer(TransactionCase):
    def setUp(self):
        super().setUp()
        self.norm = self.env["omnichannel.messenger.normalizer"]
        self.channel = self.env.ref(
            "ewin_omnichannel_messenger.channel_messenger")
        self.account = self.env["omnichannel.account"].create({
            "name": "MG", "channel_id": self.channel.id, "mg_page_id": "PAGE1"})

    def _messaging(self, message):
        return {"sender": {"id": "USER1"}, "recipient": {"id": "PAGE1"},
                "timestamp": 1700000000000, "message": message}

    def test_text_message(self):
        m = self._messaging({"mid": "m_1", "text": "Hello"})
        ev = self.norm.normalize_messaging(self.account, m)
        self.assertEqual(ev["message"]["type"], "text")
        self.assertEqual(ev["message"]["text"], "Hello")
        self.assertEqual(ev["external_user"]["id"], "USER1")
        self.assertEqual(ev["conversation"]["external_id"], "USER1")
        self.assertEqual(ev["event_id"], "messenger:msg:m_1")

    def test_image_attachment_produces_file_spec(self):
        m = self._messaging({"mid": "m_2", "attachments": [{
            "type": "image",
            "payload": {"url": "https://cdn.example/a.jpg"}}]})
        ev = self.norm.normalize_messaging(self.account, m)
        self.assertEqual(ev["message"]["type"], "image")
        spec = ev["message"]["attachments"][0]
        self.assertEqual(spec["url"], "https://cdn.example/a.jpg")
        self.assertEqual(spec["type"], "image")

    def test_sticker_is_typed_as_sticker(self):
        m = self._messaging({"mid": "m_3", "attachments": [{
            "type": "image",
            "payload": {"url": "https://cdn.example/s.png",
                        "sticker_id": 369239263222822}}]})
        ev = self.norm.normalize_messaging(self.account, m)
        self.assertEqual(ev["message"]["type"], "sticker")

    def test_location_renders_text_no_file(self):
        m = self._messaging({"mid": "m_4", "attachments": [{
            "type": "location",
            "payload": {"coordinates": {"lat": 1.5, "long": 2.5}}}]})
        ev = self.norm.normalize_messaging(self.account, m)
        self.assertEqual(ev["message"]["type"], "location")
        self.assertIn("1.5", ev["message"]["text"])
        self.assertEqual(ev["message"]["attachments"], [])

    def test_missing_mid_returns_none(self):
        m = self._messaging({"text": "no id"})
        self.assertIsNone(self.norm.normalize_messaging(self.account, m))

    def test_postback_becomes_text(self):
        messaging = {"sender": {"id": "USER1"}, "recipient": {"id": "PAGE1"},
                     "timestamp": 1700000000000,
                     "postback": {"mid": "m_pb", "title": "Get Started",
                                  "payload": "GET_STARTED"}}
        ev = self.norm.normalize_postback(self.account, messaging)
        self.assertEqual(ev["message"]["type"], "text")
        self.assertEqual(ev["message"]["text"], "Get Started")
        self.assertEqual(ev["event_id"], "messenger:msg:m_pb")

    def test_iter_messaging_classifies_events(self):
        payload = {"object": "page", "entry": [{"messaging": [
            {"sender": {"id": "U"}, "message": {"mid": "m", "text": "x"}},
            {"sender": {"id": "U"}, "message": {"mid": "e", "is_echo": True}},
            {"sender": {"id": "U"}, "delivery": {"watermark": 1}},
            {"sender": {"id": "U"}, "read": {"watermark": 1}},
            {"sender": {"id": "U"}, "postback": {"payload": "P"}},
        ]}]}
        kinds = [k for k, _e, _m in self.norm.iter_messaging(payload)]
        self.assertEqual(
            kinds, ["message", "echo", "delivery", "read", "postback"])
