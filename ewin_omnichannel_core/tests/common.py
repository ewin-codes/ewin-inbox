from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.tests.common import TransactionCase


class OmnichannelCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.channel = cls.env["omnichannel.channel"].create(
            {"name": "Test Channel", "code": "test",
             "capabilities": {"text": True, "image": True, "document": True}}
        )

    def _fake_connector(self):
        """Stand in for a channel connector.

        The core's test channel has no connector addon behind it, so a real
        delivery attempt would raise — patching the lookup keeps these suites
        independent of which connector modules happen to be installed.
        ``send_message`` marks the message sent, exactly as every real
        connector does.
        """
        connector = MagicMock()

        def send_message(account, message):
            message.write({
                "state": "sent",
                "external_message_id": "ext-1",
                "sent_at": fields.Datetime.now(),
            })
            return True

        connector.send_message.side_effect = send_message
        return connector

    def _with_connector(self, connector):
        """Patch account._get_connector for the duration of a `with` block."""
        return patch.object(
            type(self.env["omnichannel.account"]), "_get_connector",
            return_value=connector)
