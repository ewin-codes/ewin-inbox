from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase


class NotifyCase(TransactionCase):
    """One company, one conversation, one notifier — the shape every test needs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # A channel code of its own: omnichannel.channel.code is unique, and a
        # database may already carry the real 'telegram' channel.
        cls.channel = cls.env["omnichannel.channel"].create({
            "name": "Notify Test Channel", "code": "notifytest",
            "capabilities": {"text": True}})
        cls.account = cls.env["omnichannel.account"].create({
            "name": "Test Account", "channel_id": cls.channel.id})
        cls.identity = cls.env["omnichannel.identity"].create({
            "account_id": cls.account.id, "external_id": "4242",
            "display_name": "Ann Brown", "username": "ann"})
        cls.conversation = cls.env["omnichannel.conversation"].create({
            "name": "Ann Brown", "account_id": cls.account.id,
            "identity_id": cls.identity.id})
        cls.notifier = cls.env["omnichannel.telegram.notifier"].create({
            "name": "Notifier", "bot_token": "BOT-TOKEN",
            "bot_username": "ewin_notify_bot", "group_chat_id": "-100777",
            "throttle_minutes": 10, "webhook_secret": "SECRET"})

    def _fake_client(self):
        """Stand in for the Bot API. Records what would have been sent."""
        client = MagicMock()
        client.get_me.return_value = {"id": 1, "username": "ewin_notify_bot"}
        client.send_message.return_value = {"message_id": 1}
        return client

    def _with_client(self, client):
        """Patch notifier._client() for the duration of a `with` block."""
        return patch.object(
            type(self.env["omnichannel.telegram.notifier"]), "_client",
            return_value=client)

    def _inbound(self, body="<p>Hello there</p>", **extra):
        """Record a customer message on the shared conversation."""
        vals = {
            "conversation_id": self.conversation.id,
            "direction": "inbound", "sender_type": "customer",
            "message_type": "text", "body": body, "state": "received",
        }
        vals.update(extra)
        return self.env["omnichannel.message"].create(vals)

    def _jobs(self):
        return self.env["omnichannel.job"].search(
            [("method", "=", "send_notification")])
