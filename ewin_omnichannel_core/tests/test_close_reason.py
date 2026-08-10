from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestCloseReason(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "123"})
        self.reason = self.env.ref(
            "ewin_omnichannel_core.close_reason_resolved")

    def _new_conv(self):
        return self.env["omnichannel.conversation"].create({
            "name": "Conv", "account_id": self.account.id,
            "identity_id": self.identity.id})

    def test_shipped_reasons_are_shared_across_companies(self):
        """The reasons ship as data with no company, so a second company sees
        them without anyone re-creating the list."""
        reasons = self.env["omnichannel.close.reason"].search([])
        self.assertGreaterEqual(len(reasons), 5)
        for xmlid in ("close_reason_resolved", "close_reason_no_answer",
                      "close_reason_spam", "close_reason_duplicate",
                      "close_reason_elsewhere"):
            reason = self.env.ref("ewin_omnichannel_core.%s" % xmlid)
            self.assertFalse(
                reason.company_id,
                "%s must be shared, not owned by one company" % xmlid)

    def test_reasons_are_ordered_by_sequence_not_by_name(self):
        """Sequence is what an administrator drags; it has to beat the
        alphabet, or reordering the list does nothing."""
        model = self.env["omnichannel.close.reason"]
        last = model.create({"name": "AAA last", "sequence": 900})
        first = model.create({"name": "ZZZ first", "sequence": 1})
        ordered = model.search([("id", "in", (first | last).ids)])
        self.assertEqual(ordered.ids, [first.id, last.id])

    def test_reason_name_unique_among_shared_reasons(self):
        """This is the regression test for the gap a plain SQL
        unique(name, company_id) constraint leaves open: Postgres treats
        two empty company_id values as distinct, so it never fires for two
        shared reasons — exactly the common case, since every shipped
        default is shared."""
        model = self.env["omnichannel.close.reason"]
        model.create({"name": "Escalated", "company_id": False})
        with self.assertRaises(ValidationError):
            model.create({"name": "Escalated", "company_id": False})

    def test_reason_name_unique_within_a_company(self):
        model = self.env["omnichannel.close.reason"]
        model.create({"name": "Escalated", "company_id": self.company.id})
        with self.assertRaises(ValidationError):
            model.create(
                {"name": "Escalated", "company_id": self.company.id})

    def test_reason_name_may_repeat_across_scopes(self):
        """The same label may exist once shared and once owned by a
        specific company: the uniqueness scope is the (name, company)
        pair, not the name alone."""
        model = self.env["omnichannel.close.reason"]
        shared = model.create({"name": "Escalated", "company_id": False})
        owned = model.create(
            {"name": "Escalated", "company_id": self.company.id})
        self.assertNotEqual(shared, owned)

    def test_archived_reason_may_share_a_name_with_an_active_one(self):
        """Archiving exists so a name can be retired and reused: the
        uniqueness invariant only covers active rows, so a duplicate of an
        archived reason must stay legal."""
        model = self.env["omnichannel.close.reason"]
        archived = model.create({"name": "Escalated", "company_id": False})
        archived.active = False
        active = model.create({"name": "Escalated", "company_id": False})
        self.assertFalse(archived.active)
        self.assertTrue(active.active)

    def test_reactivating_a_reason_re_triggers_uniqueness_check(self):
        """Regression test: archive a reason, let a new one take its name,
        then reactivate the first. The write touches only `active` — if
        that field isn't wired into the check, two active duplicates end
        up coexisting with no error."""
        model = self.env["omnichannel.close.reason"]
        archived = model.create({"name": "Escalated", "company_id": False})
        archived.active = False
        model.create({"name": "Escalated", "company_id": False})
        with self.assertRaises(ValidationError):
            archived.active = True

    def _set_policy(self, value):
        self.env["ir.config_parameter"].sudo().set_param(
            "ewin_omnichannel.close_reason_policy", value)

    def test_policy_defaults_to_off(self):
        """An existing installation must keep closing conversations the way it
        always did until an administrator turns the question on."""
        self._set_policy("")
        self.assertEqual(
            self.env["omnichannel.conversation"]._close_reason_policy(), "off")

    def test_policy_follows_the_setting(self):
        for value in ("optional", "required", "off"):
            self._set_policy(value)
            self.assertEqual(
                self.env["omnichannel.conversation"]._close_reason_policy(),
                value)
