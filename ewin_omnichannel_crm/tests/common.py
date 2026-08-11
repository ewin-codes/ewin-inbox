from odoo.tests.common import TransactionCase


class OmnichannelCrmCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env["omnichannel.channel"].create(
            {"name": "Test Channel", "code": "test",
             "capabilities": {"text": True}})
        cls.account = cls.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": cls.channel.id})
        cls.note_subtype = cls.env.ref("mail.mt_note")

    def setUp(self):
        super().setUp()
        # mail_create_nolog: a bare create() logs its own "Contact/Lead
        # created" mail.mt_note, indistinguishable from a mirrored copy to
        # _notes() below.
        self.partner = self.env["res.partner"].with_context(
            mail_create_nolog=True).create({"name": "Ada Lovelace"})
        self.identity = self.env["omnichannel.identity"].create({
            "account_id": self.account.id, "external_id": "123",
            "display_name": "Ada Lovelace", "phone": "+490001",
            "email": "ada@example.com"})
        self.lead = self.env["crm.lead"].with_context(
            mail_create_nolog=True).create({"name": "Bulk order"})
        self.history = self.env["omnichannel.history.service"]

    def _new_conv(self, **vals):
        return self.env["omnichannel.conversation"].create(dict({
            "name": "Conv", "account_id": self.account.id,
            "identity_id": self.identity.id}, **vals))

    def _new_message(self, conv, body="Hello", **vals):
        return self.env["omnichannel.message"].create(dict({
            "conversation_id": conv.id, "direction": "inbound",
            "sender_type": "customer", "body": body}, **vals))

    def _notes(self, record):
        return record.message_ids.filtered(
            lambda m: m.subtype_id == self.note_subtype)
