from odoo.tests import tagged

from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestInboundAttachments(OmnichannelCase):
    """A customer's file has to arrive as a file.

    Between the connector's download and the operator's thread there are two
    places where one quietly disappears: ``message_post`` keeps only the
    attachments the *calling* user drafted on a composer, and an inbound
    arrives in a webhook request that runs as the public user; and an
    attachment that hangs off no record at all is readable by its creator
    alone. Either one leaves the operator with a notification about a file
    that is not there.
    """

    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        # Exactly what a connector holds inside request.env[...].sudo():
        # the public user, with sudo raised.
        self.webhook = self.env(user=self.env.ref("base.public_user"), su=True)

    def _event(self):
        return {
            "event_id": "test:update:1",
            "external_message_id": "1",
            "external_user": {"id": "123", "name": "Ivan Petrov"},
            "conversation": {"external_id": "123", "type": "private"},
            "message": {
                "type": "image", "text": "Here is the parcel",
                "attachments": [{"filename": "parcel.jpg"}],
                "reply_to_external_message_id": None,
            },
            "raw_payload": {},
        }

    def _connector(self):
        """A connector that downloads like every real one does: the bytes are
        stored as a bare ir.attachment, in the environment of the request that
        is handling the webhook."""
        connector = self._fake_connector()
        connector.download_attachment.side_effect = lambda account, spec: (
            account.env["ir.attachment"].create({
                "name": spec["filename"], "raw": b"binary",
                "mimetype": "image/jpeg"}))
        return connector

    def _inbound(self):
        with self._with_connector(self._connector()):
            return self.webhook["omnichannel.routing.service"].process_event(
                self.account.with_env(self.webhook), self._event())

    def test_the_customer_file_reaches_the_mirrored_thread(self):
        message = self._inbound()
        self.assertTrue(message.attachment_ids, "the file was not downloaded")
        self.assertEqual(message.mail_message_id.attachment_ids,
                         message.attachment_ids)

    def test_the_customer_file_is_anchored_on_the_conversation(self):
        """Access to the file follows access to the conversation it belongs
        to — the same answer in the inbox, in the mirror and in the customer's
        chatter, and one that survives the public user who created it."""
        message = self._inbound()
        attachment = message.attachment_ids
        self.assertEqual(attachment.res_model, "omnichannel.conversation")
        self.assertEqual(attachment.res_id, message.conversation_id.id)

    def test_an_operator_can_read_the_customer_file(self):
        """ir.attachment.check refuses an attachment with no record behind it
        to everyone but its creator; only a settings admin escapes that rule,
        which is why an installation notices this late."""
        operator = self.env["res.users"].create({
            "name": "Operator", "login": "inbound_att_operator",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})
        message = self._inbound()
        message.attachment_ids.with_user(operator).check("read")
