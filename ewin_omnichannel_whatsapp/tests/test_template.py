from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTemplate(TransactionCase):
    def setUp(self):
        super().setUp()
        self.channel = self.env.ref("ewin_omnichannel_whatsapp.channel_whatsapp")
        self.account = self.env["omnichannel.account"].create({
            "name": "WA", "channel_id": self.channel.id,
            "wa_phone_number_id": "PN1", "wa_access_token": "T",
            "wa_waba_id": "WABA1"})

    def _remote(self):
        return [
            {"name": "hello", "language": "en_US", "category": "UTILITY",
             "status": "APPROVED", "components": [
                 {"type": "BODY", "text": "Hi {{1}}, order {{2}} ready."}]},
            {"name": "old", "language": "en_US", "category": "MARKETING",
             "status": "APPROVED", "components": [
                 {"type": "BODY", "text": "Promo"}]},
        ]

    def test_sync_upserts_and_archives(self):
        connector = self.env["omnichannel.connector.whatsapp"]
        with patch("odoo.addons.ewin_omnichannel_whatsapp.services."
                   "whatsapp_api_client.WhatsAppApiClient.list_templates",
                   return_value=self._remote()):
            connector.sync_templates(self.account)
        tpls = self.env["omnichannel.whatsapp.template"].search([
            ("account_id", "=", self.account.id)])
        self.assertEqual(len(tpls), 2)
        hello = tpls.filtered(lambda t: t.name == "hello")
        self.assertEqual(hello.variables_count, 2)
        # second sync without 'old' archives it
        with patch("odoo.addons.ewin_omnichannel_whatsapp.services."
                   "whatsapp_api_client.WhatsAppApiClient.list_templates",
                   return_value=self._remote()[:1]):
            connector.sync_templates(self.account)
        old = self.env["omnichannel.whatsapp.template"].search([
            ("account_id", "=", self.account.id), ("name", "=", "old")])
        self.assertFalse(old.active)

    def test_build_components_fills_variables(self):
        tpl = self.env["omnichannel.whatsapp.template"].create({
            "account_id": self.account.id, "name": "hello",
            "language": "en_US", "status": "APPROVED", "variables_count": 2,
            "components": [{"type": "BODY", "text": "Hi {{1}}, order {{2}}."}]})
        comps = tpl._build_components(["Ann", "A-100"])
        body = [c for c in comps if c["type"] == "body"][0]
        self.assertEqual(body["parameters"][0]["text"], "Ann")
        self.assertEqual(body["parameters"][1]["text"], "A-100")
