from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestConnectorInbound(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env.ref("ewin_omnichannel_telegram.channel_telegram")
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Bot", "channel_id": cls.channel.id,
            "tg_bot_token": "T", "tg_webhook_secret": "S"})
        cls.connector = cls.env["omnichannel.connector.telegram"]

    def _update(self, uid=123, text="Hello", mid=987, upd=111):
        return {"update_id": upd, "message": {
            "message_id": mid, "date": 1700000000,
            "from": {"id": uid, "first_name": "Ivan", "username": "ivan"},
            "chat": {"id": uid, "type": "private"}, "text": text}}

    def test_inbound_text_creates_message(self):
        headers = {"X-Telegram-Bot-Api-Secret-Token": "S"}
        self.connector.parse_webhook(self.account, self._update(), headers)
        conv = self.env["omnichannel.conversation"].search(
            [("account_id", "=", self.account.id)])
        self.assertEqual(len(conv), 1)
        self.assertEqual(
            conv.omni_message_ids[0].body and "Hello" in conv.omni_message_ids[0].body,
            True)

    def test_bad_secret_rejected(self):
        res = self.connector.parse_webhook(
            self.account, self._update(),
            {"X-Telegram-Bot-Api-Secret-Token": "WRONG"})
        self.assertFalse(res)
        self.assertFalse(self.env["omnichannel.conversation"].search(
            [("account_id", "=", self.account.id)]))

    def test_duplicate_update_single_message(self):
        headers = {"X-Telegram-Bot-Api-Secret-Token": "S"}
        self.connector.parse_webhook(self.account, self._update(upd=222), headers)
        self.connector.parse_webhook(self.account, self._update(upd=222), headers)
        msgs = self.env["omnichannel.message"].search(
            [("account_id", "=", self.account.id)])
        self.assertEqual(len(msgs), 1)
