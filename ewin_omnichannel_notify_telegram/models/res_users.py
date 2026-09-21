import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

# How long a freshly issued link stays usable. Short enough that a token left
# in a chat window or a clipboard stops being a key; long enough to survive a
# weekend.
LINK_TOKEN_HOURS = 24


class ResUsers(models.Model):
    _inherit = "res.users"

    omni_tg_chat_id = fields.Char(
        string="Telegram Chat", copy=False, index=True, readonly=True,
        help="Filled in when this user opens the notification bot's personal "
             "link and presses Start.")
    omni_tg_username = fields.Char(
        string="Telegram Username", copy=False, readonly=True)
    # The token is the credential: whoever opens the link receives this user's
    # notifications from then on. res.users is readable by every internal
    # user, so the field is closed to all but system administrators and the
    # link itself is handed over through a transient wizard.
    omni_tg_link_token = fields.Char(
        string="Telegram Link Token", copy=False, groups="base.group_system")
    omni_tg_link_expires_at = fields.Datetime(
        string="Telegram Link Expiry", copy=False, groups="base.group_system")

    @property
    def SELF_READABLE_FIELDS(self):
        # So a user sees their own binding in Preferences without holding any
        # right on other users' records.
        return super().SELF_READABLE_FIELDS + [
            "omni_tg_chat_id", "omni_tg_username"]

    def _omni_tg_check_own_record(self):
        """Only the person themselves, or an administrator onboarding them."""
        self.ensure_one()
        if self == self.env.user:
            return
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("You can only connect your own Telegram."))

    def action_omni_tg_link(self):
        """Issue a fresh one-time link and show it to whoever pressed the
        button.

        The wizard is created without ``sudo``: a transient record belongs to
        its creator, and one created by the superuser would be unreadable by
        the very person it was made for.
        """
        self._omni_tg_check_own_record()
        notifier = self.env["omnichannel.telegram.notifier"]._for_company(
            self.env.company)
        if not notifier:
            raise UserError(_(
                "No Telegram notifier is configured for %s.",
                self.env.company.display_name))
        if not notifier.bot_username:
            raise UserError(_(
                "The notifier does not know its bot yet. Open it and press "
                "Check Connection first."))
        token = uuid.uuid4().hex
        self.sudo().write({
            "omni_tg_link_token": token,
            "omni_tg_link_expires_at": fields.Datetime.add(
                fields.Datetime.now(), hours=LINK_TOKEN_HOURS),
        })
        wizard = self.env["omnichannel.telegram.link"].create({
            "user_id": self.id,
            "bot_username": notifier.bot_username,
            "url": f"https://t.me/{notifier.bot_username}?start={token}",
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Connect Telegram"),
            "res_model": "omnichannel.telegram.link",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_omni_tg_unlink(self):
        """Stop notifying this user in Telegram, and void any pending link."""
        self._omni_tg_check_own_record()
        self.sudo().write({
            "omni_tg_chat_id": False, "omni_tg_username": False,
            "omni_tg_link_token": False, "omni_tg_link_expires_at": False,
        })
        return True

    @api.model
    def _omni_tg_consume_link_token(self, token):
        """Return the user a one-time token belongs to, and burn it.

        Burned even when it has expired: a token that was presented is spent
        either way, so a leaked one cannot be tried again in the hope that the
        clock was wrong.
        """
        empty = self.browse()
        if not token:
            return empty
        user = self.sudo().search([("omni_tg_link_token", "=", token)], limit=1)
        if not user:
            return empty
        expiry = user.omni_tg_link_expires_at
        user.write({"omni_tg_link_token": False,
                    "omni_tg_link_expires_at": False})
        if expiry and expiry < fields.Datetime.now():
            return empty
        return user
