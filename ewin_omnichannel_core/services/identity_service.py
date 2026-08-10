from odoo import api, fields, models


class IdentityService(models.AbstractModel):
    _name = "omnichannel.identity.service"
    _description = "Omnichannel Identity Service"

    @api.model
    def find_or_create(self, account, external_user):
        Identity = self.env["omnichannel.identity"]
        ext_id = str(external_user["id"])
        ident = Identity.search([
            ("account_id", "=", account.id),
            ("external_id", "=", ext_id),
        ], limit=1)
        profile = {
            "display_name": external_user.get("name"),
            "username": external_user.get("username"),
            "phone": external_user.get("phone"),
            "language_code": external_user.get("language_code"),
        }
        if ident:
            vals = {"last_seen_at": fields.Datetime.now()}
            vals.update({k: v for k, v in profile.items() if v})
            if external_user.get("raw"):
                vals["raw_metadata"] = external_user["raw"]
            ident.write(vals)
            return ident
        vals = {k: v for k, v in profile.items() if v is not None}
        vals.update({
            "account_id": account.id,
            "external_id": ext_id,
            "last_seen_at": fields.Datetime.now(),
            "raw_metadata": external_user.get("raw", {}),
        })
        return Identity.create(vals)

    @api.model
    def ensure_partner(self, identity, auto_create=True):
        if identity.partner_id:
            return identity.partner_id
        if not auto_create:
            return self.env["res.partner"]
        name = self._build_partner_name(identity)
        vals = {
            "name": name,
            "omni_source": identity.account_id.channel_id.name,
            "omni_external_id": identity.external_id,
            "omni_username": identity.username,
            "omni_first_contact": identity.first_seen_at,
        }
        # mail_create_nolog: a bare create() would log its own "Contact
        # created" note, indistinguishable from a mirrored history entry and
        # redundant with the customer's own first message landing right
        # after it once the conversation links back here.
        partner = self.env["res.partner"].with_context(
            mail_create_nolog=True).create(vals)
        identity.partner_id = partner
        return partner

    @api.model
    def _build_partner_name(self, identity):
        if identity.display_name:
            return identity.display_name
        if identity.username:
            return f"{identity.account_id.channel_id.name} @{identity.username}"
        return f"{identity.account_id.channel_id.name} user {identity.external_id}"
