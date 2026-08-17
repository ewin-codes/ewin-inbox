from odoo.tests import tagged
from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestMirrorAccess(OmnichannelCase):
    """The mirror discuss.channel carries the whole conversation — customer
    messages, attachments and internal notes. Whatever the inbox refuses to
    show must not be readable through the mirror either.
    """

    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Acc", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "1"})
        self.conv = self.env["omnichannel.conversation"].create({
            "name": "Customer", "account_id": self.account.id,
            "identity_id": self.identity.id})
        self.employee = self.env["res.users"].create({
            "name": "Warehouse", "login": "mirror_employee",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])]})
        self.operator_a = self._operator("mirror_op_a")
        self.operator_b = self._operator("mirror_op_b")

    def _operator(self, login):
        return self.env["res.users"].create({
            "name": login, "login": login,
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_operator").id)]})

    def test_employee_without_an_inbox_group_cannot_read_the_mirror(self):
        channel = self.conv._ensure_discuss_channel()
        visible = self.env["discuss.channel"].with_user(self.employee).search([])
        self.assertNotIn(channel, visible)

    def test_operator_can_read_the_mirror(self):
        channel = self.conv._ensure_discuss_channel()
        visible = self.env["discuss.channel"].with_user(self.operator_a).search([])
        self.assertIn(channel, visible)

    def test_reply_from_an_operator_outside_the_conversation_is_not_sent(self):
        """Membership of the channel is not authority over the customer: the
        forward is allowed by the conversation, which has its own record rule.
        """
        self.conv.operator_id = self.operator_a
        channel = self.conv._ensure_discuss_channel()
        channel.sudo().add_members(
            partner_ids=self.operator_b.partner_id.ids,
            post_joined_message=False)
        connector = self._fake_connector()
        with self._with_connector(connector):
            channel.with_user(self.operator_b).message_post(
                body="Wire the refund to IBAN ...", message_type="comment",
                subtype_xmlid="mail.mt_comment")
        self.assertFalse(connector.send_message.called)
        self.assertFalse(self.env["omnichannel.message"].search([
            ("conversation_id", "=", self.conv.id),
            ("direction", "=", "outbound")]))

    def test_reply_from_the_assigned_operator_is_sent(self):
        self.conv.operator_id = self.operator_a
        channel = self.conv._ensure_discuss_channel()
        connector = self._fake_connector()
        with self._with_connector(connector):
            channel.with_user(self.operator_a).message_post(
                body="On its way.", message_type="comment",
                subtype_xmlid="mail.mt_comment")
        self.assertTrue(connector.send_message.called)
        outbound = self.env["omnichannel.message"].search([
            ("conversation_id", "=", self.conv.id),
            ("direction", "=", "outbound")])
        self.assertEqual(len(outbound), 1)
