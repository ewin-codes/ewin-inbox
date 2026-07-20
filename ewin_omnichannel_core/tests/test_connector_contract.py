from odoo.tests import tagged

from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestConnectorContract(OmnichannelCase):
    def test_abstract_methods_raise(self):
        connector = self.env["omnichannel.connector"]
        with self.assertRaises(NotImplementedError):
            connector.send_message(None, None)
