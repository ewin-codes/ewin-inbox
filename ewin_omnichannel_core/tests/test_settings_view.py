from lxml import etree

from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestSettingsView(TransactionCase):
    """Our settings must be a *block inside* the standard settings form.

    A standalone primary view for ``res.config.settings`` does more than look
    different: it hides every other module's settings. The Settings action
    carries no ``view_id``, so Odoo resolves the form through
    ``default_view()``, which searches ``ir.ui.view`` in ``_order``
    ``priority,name,id``. At the same priority the *name* decides, and
    ``ewin.…`` sorts before ``res.config.settings.view.form`` — an own primary
    view therefore wins the lookup and General Settings, CRM, Sales … all
    disappear from Settings.
    """

    def test_settings_action_still_opens_the_standard_form(self):
        """The regression test for the hijack: whatever this module ships,
        the default form of res.config.settings stays the one every other
        module extends."""
        self.assertEqual(
            self.env["ir.ui.view"].default_view("res.config.settings", "form"),
            self.env.ref("base.res_config_settings_view_form").id)

    def test_our_view_extends_that_form(self):
        view = self.env.ref(
            "ewin_omnichannel_core.res_config_settings_view_form")
        self.assertEqual(view.mode, "extension")
        self.assertEqual(
            view.inherit_id,
            self.env.ref("base.res_config_settings_view_form"))

    def test_the_form_carries_our_settings_in_their_own_app_block(self):
        """Read the combined arch the way the client does — through the
        default view — so the assertion covers the inheritance actually
        being applied, not just the source arch of our own record."""
        arch = etree.fromstring(
            self.env["res.config.settings"].get_view(view_type="form")["arch"])
        apps = arch.xpath("//app[@name='ewin_omnichannel_core']")
        self.assertEqual(
            len(apps), 1,
            "the settings sidebar needs exactly one EWIN Inbox entry")
        for field in ("omni_send_shortcut", "omni_close_reason_policy"):
            self.assertTrue(
                apps[0].xpath(".//field[@name='%s']" % field),
                "%s must live inside the EWIN Inbox block" % field)

    def test_the_menu_opens_settings_on_our_own_block(self):
        """Configuration → Settings jumps straight to our section: the
        client picks the initial tab from the action's `module` context key,
        matched against the <app name="…"> above."""
        action = self.env.ref("ewin_omnichannel_core.action_omni_settings")
        self.assertEqual(
            safe_eval(action.context).get("module"), "ewin_omnichannel_core")
