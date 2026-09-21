from odoo.tests import TransactionCase, tagged

from odoo.addons.ewin_omnichannel_core.tools.security import secret_equals


@tagged("post_install", "-at_install")
class TestSecretEquals(TransactionCase):
    """Every webhook in the suite compares its secret through this one
    function, so the guarantees it makes are tested once, here."""

    def test_equal_secrets_match(self):
        self.assertTrue(secret_equals("s3cret", "s3cret"))

    def test_different_secrets_do_not_match(self):
        self.assertFalse(secret_equals("wrong", "s3cret"))

    def test_an_empty_expected_value_refuses(self):
        # Nothing to verify against is a reason to reject, not to accept:
        # a webhook URL is not a credential. An empty presented value must
        # not become the key to an account whose secret was never set.
        self.assertFalse(secret_equals("", ""))
        self.assertFalse(secret_equals("anything", ""))

    def test_a_non_ascii_presented_value_is_an_ordinary_mismatch(self):
        # The defect this function exists for: hmac.compare_digest raises
        # TypeError on a non-ASCII str, and a header value reaches Python
        # decoded as Latin-1. Raising here would answer differently from a
        # mismatch and turn every such route into an existence oracle.
        self.assertFalse(secret_equals("\xe9", "s3cret"))
        self.assertFalse(secret_equals("s3cret–", "s3cret"))

    def test_a_non_ascii_expected_value_is_an_ordinary_mismatch(self):
        # An administrator is free to paste a secret with an accent in it.
        self.assertFalse(secret_equals("s3cret", "s\xe9cret"))
        self.assertTrue(secret_equals("s\xe9cret", "s\xe9cret"))
