from odoo.tests import tagged
from odoo.tests.common import TransactionCase

OUR_FILE = "ewin_omnichannel_core/static/src/xml/omni_navbar.xml"


@tagged("post_install", "-at_install")
class TestMenuBadgeAssets(TransactionCase):
    """The badges hang off Odoo's own navbar templates.

    Odoo resolves OWL template inheritance in the browser, where a target that
    has moved fails as a console error and an app that renders without its
    badges — silent, and only ever seen by whoever opens that one app. This
    runs the same lookups here, against the Odoo source actually installed, so
    an upgrade that renames a navbar template fails the suite instead.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        blocks = cls.env["ir.qweb"]._get_asset_bundle("web.assets_backend").xml()
        cls.templates = {}
        cls.extensions = []
        for block in blocks:
            if block["type"] == "templates":
                for tree, _url, _inherit in block["templates"]:
                    if tree.get("t-name"):
                        cls.templates[tree.get("t-name")] = tree
            else:
                for inherit_from, entries in block["extensions"].items():
                    for tree, url in entries:
                        cls.extensions.append((inherit_from, tree, url))
        cls.ours = [(parent, tree) for parent, tree, url in cls.extensions
                    if OUR_FILE in url]

    def test_the_badge_template_is_in_the_backend_bundle(self):
        self.assertIn("ewin_omnichannel_core.MenuBadge", self.templates)

    def test_every_navbar_template_we_extend_still_exists(self):
        self.assertEqual(
            len(self.ours), 3,
            "the top bar, the More dropdown and the phone sidebar")
        for parent, _tree in self.ours:
            self.assertIn(
                parent, self.templates,
                "%s is gone from Odoo — the badge would vanish with it" % parent)

    def test_every_xpath_we_aim_at_the_navbar_finds_its_node(self):
        for parent, tree in self.ours:
            parent_tree = self.templates[parent]
            operations = [node for node in tree if node.tag == "xpath"]
            self.assertTrue(operations, "an inherit block with no xpath")
            for operation in operations:
                expr = operation.get("expr")
                found = parent_tree.xpath(expr)
                self.assertEqual(
                    len(found), 1,
                    "%s in %s matched %s nodes" % (expr, parent, len(found)))
