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
