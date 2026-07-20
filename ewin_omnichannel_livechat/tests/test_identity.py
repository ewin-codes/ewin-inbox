import uuid

from .common import LivechatCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestLivechatIdentity(LivechatCase):
    def _website(self):
        return self.env["website"].search([], limit=1)

    def test_logged_in_visitor_keys_on_partner(self):
        # website.visitor.access_token defaults via a method that requires an
        # HTTP request (raises outside the frontend); set it explicitly. A
        # non-32-char access_token is how core website.visitor itself encodes
        # "this visitor is a logged-in partner" (see _compute_partner_id), so
        # this also drives partner_id without needing an inverse.
        partner = self.env["res.partner"].create({"name": "Jane Client"})
        visitor = self.env["website.visitor"].create({
            "website_id": self._website().id, "partner_id": partner.id,
            "access_token": str(partner.id)})
        channel = self._make_session(visitor=visitor)
        msg = self._visitor_post(channel, author=partner)
        event = self.env["omnichannel.livechat.normalizer"].normalize_message(
            self.account, channel, msg)
        self.assertEqual(event["external_user"]["id"], f"partner:{partner.id}")
        self.assertEqual(event["external_user"]["partner_id"], partner.id)

    def test_anonymous_visitor_keys_on_website_visitor(self):
        # A 32-char hex access_token is the anonymous-visitor shape core
        # itself generates (see website_visitor._get_access_token).
        visitor = self.env["website.visitor"].create({
            "website_id": self._website().id,
            "access_token": uuid.uuid4().hex})
        channel = self._make_session(visitor=visitor)
        msg = self._visitor_post(channel)
        event = self.env["omnichannel.livechat.normalizer"].normalize_message(
            self.account, channel, msg)
        self.assertEqual(event["external_user"]["id"], f"visitor:{visitor.id}")

    def test_guest_fallback(self):
        guest = self.env["mail.guest"].create({"name": "Guest Q"})
        channel = self._make_session(guest=guest)
        msg = self._visitor_post(channel)
        event = self.env["omnichannel.livechat.normalizer"].normalize_message(
            self.account, channel, msg)
        self.assertEqual(event["external_user"]["id"], f"guest:{guest.id}")

    def test_operator_message_is_not_visitor(self):
        channel = self._make_session()
        normalizer = self.env["omnichannel.livechat.normalizer"]
        op_msg = channel.with_context(omni_livechat_outbound=True).message_post(
            body="hi from op", author_id=self.bridge_user.partner_id.id,
            message_type="comment", subtype_xmlid="mail.mt_comment")
        self.assertFalse(normalizer.is_visitor_message(channel, op_msg))
