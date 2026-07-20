from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNormalizer(TransactionCase):
    def setUp(self):
        super().setUp()
        self.norm = self.env["omnichannel.whatsapp.normalizer"]
        self.channel = self.env.ref("ewin_omnichannel_whatsapp.channel_whatsapp")
        self.account = self.env["omnichannel.account"].create({
            "name": "WA", "channel_id": self.channel.id,
            "wa_phone_number_id": "PN1"})

    def _text_value(self):
        return {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": "PN1"},
            "contacts": [{"profile": {"name": "Ann"}, "wa_id": "15551230000"}],
            "messages": [{"from": "15551230000", "id": "wamid.1",
                          "timestamp": "1700000000", "type": "text",
                          "text": {"body": "Hello"}}],
        }

    def test_text_message(self):
        value = self._text_value()
        ev = self.norm.normalize_message(
            self.account, value, value["messages"][0], value["contacts"])
        self.assertEqual(ev["message"]["type"], "text")
        self.assertEqual(ev["message"]["text"], "Hello")
        self.assertEqual(ev["external_user"]["phone"], "15551230000")
        self.assertEqual(ev["external_user"]["name"], "Ann")
        self.assertEqual(ev["conversation"]["external_id"], "15551230000")
        self.assertEqual(ev["event_id"], "whatsapp:msg:wamid.1")

    def test_image_message_produces_file_spec(self):
        value = self._text_value()
        value["messages"][0] = {
            "from": "15551230000", "id": "wamid.2", "timestamp": "1700000001",
            "type": "image", "image": {"id": "MID9", "mime_type": "image/jpeg",
                                        "caption": "look"}}
        ev = self.norm.normalize_message(
            self.account, value, value["messages"][0], value["contacts"])
        self.assertEqual(ev["message"]["type"], "image")
        self.assertEqual(ev["message"]["text"], "look")
        spec = ev["message"]["attachments"][0]
        self.assertEqual(spec["media_id"], "MID9")
        self.assertEqual(spec["mime_type"], "image/jpeg")

    def test_location_renders_text_no_file(self):
        value = self._text_value()
        value["messages"][0] = {
            "from": "15551230000", "id": "wamid.3", "timestamp": "1",
            "type": "location",
            "location": {"latitude": 1.5, "longitude": 2.5}}
        ev = self.norm.normalize_message(
            self.account, value, value["messages"][0], value["contacts"])
        self.assertEqual(ev["message"]["type"], "location")
        self.assertIn("1.5", ev["message"]["text"])
        self.assertEqual(ev["message"]["attachments"], [])

    def test_reaction_renders_text(self):
        value = self._text_value()
        value["messages"][0] = {
            "from": "15551230000", "id": "wamid.4", "timestamp": "1",
            "type": "reaction",
            "reaction": {"message_id": "wamid.1", "emoji": "\U0001F44D"}}
        ev = self.norm.normalize_message(
            self.account, value, value["messages"][0], value["contacts"])
        self.assertIn("\U0001F44D", ev["message"]["text"])

    def test_iter_changes_splits_messages_and_statuses(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"id": "m1", "type": "text", "from": "1",
                          "text": {"body": "x"}}],
            "statuses": [{"id": "s1", "status": "delivered",
                          "timestamp": "1"}]}}]}]}
        kinds = [k for k, _v, _i in self.norm.iter_changes(payload)]
        self.assertEqual(sorted(kinds), ["message", "status"])
