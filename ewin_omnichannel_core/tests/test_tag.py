from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestTag(OmnichannelCase):
    def test_tag_name_unique_among_shared_tags(self):
        """The gap a SQL unique(name, company_id) leaves open: Postgres
        treats two empty company_id values as distinct, so it never fires
        for two tags shared by every company."""
        model = self.env["omnichannel.tag"]
        model.create({"name": "VIP", "company_id": False})
        with self.assertRaises(ValidationError):
            model.create({"name": "VIP", "company_id": False})

    def test_tag_name_unique_within_a_company(self):
        model = self.env["omnichannel.tag"]
        model.create({"name": "VIP", "company_id": self.company.id})
        with self.assertRaises(ValidationError):
            model.create({"name": "VIP", "company_id": self.company.id})

    def test_tag_name_may_repeat_across_scopes(self):
        model = self.env["omnichannel.tag"]
        shared = model.create({"name": "VIP", "company_id": False})
        owned = model.create({"name": "VIP", "company_id": self.company.id})
        self.assertNotEqual(shared, owned)

    def test_renaming_onto_an_existing_tag_is_refused(self):
        model = self.env["omnichannel.tag"]
        model.create({"name": "VIP", "company_id": self.company.id})
        other = model.create({"name": "Lead", "company_id": self.company.id})
        with self.assertRaises(ValidationError):
            other.name = "VIP"
