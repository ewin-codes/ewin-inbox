import uuid

from odoo import _, _lt, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.notify_api_client import TelegramNotifyClient, TelegramNotifyError

# Module-level strings use _lt: _() at import time has no language context and
# would freeze the text in the source language.
FRIENDLY_ERRORS = {
    "unauthorized": _lt("The Telegram bot token is invalid or was revoked."),
    "chat not found": _lt(
        "Telegram does not know that chat. Add the bot to the group and send "
        "/register there."),
    "bot was blocked by the user": _lt(
        "The recipient has blocked the notification bot."),
    "not enough rights": _lt("The bot may not post in that chat."),
}


class OmnichannelTelegramNotifier(models.Model):
    _name = "omnichannel.telegram.notifier"
    _description = "Telegram Notifier"
    _order = "company_id, id"

    name = fields.Char(required=True, default="Telegram notifications")
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    state = fields.Selection(
        [("draft", "Draft"), ("connected", "Connected"), ("error", "Error")],
        default="draft", required=True, index=True)
    last_error = fields.Text(readonly=True)

    bot_token = fields.Char(
        groups="ewin_omnichannel_core.group_omni_admin", copy=False,
        help="The token @BotFather issued for the notification bot. This is "
             "not the customer-facing bot of the Telegram connector.")
    bot_token_masked = fields.Char(
        string="Token", compute="_compute_bot_token_masked")
    bot_username = fields.Char(readonly=True)
    bot_external_id = fields.Char(string="Bot ID", readonly=True)
    api_base_url = fields.Char(
        required=True, default="https://api.telegram.org")

    group_chat_id = fields.Char(
        help="The chat the team shares. Used when a conversation has no "
             "operator, or the operator has not linked their Telegram. Set it "
             "by sending /register in that group.")
    throttle_minutes = fields.Integer(
        required=True, default=10,
        help="A conversation notifies at most once per this many minutes. The "
             "first message of a conversation always notifies.")

    webhook_uuid = fields.Char(
        required=True, copy=False, index=True,
        default=lambda self: uuid.uuid4().hex)
    webhook_secret = fields.Char(
        groups="ewin_omnichannel_core.group_omni_admin", copy=False)
    webhook_status = fields.Char(readonly=True, default="none")

    _sql_constraints = [
        ("webhook_uuid_uniq", "unique(webhook_uuid)",
         "Webhook UUID must be unique."),
        ("throttle_not_negative", "check(throttle_minutes >= 0)",
         "The throttle window cannot be negative."),
    ]

    @api.depends("bot_token")
    def _compute_bot_token_masked(self):
        for notifier in self:
            # sudo(): bot_token is admin-only, but this compute also backs
            # the masked field an operator sees on the same form — reading
            # the raw value here to derive a fixed-length mask is not the
            # access grant _client() exists to guard against.
            notifier.bot_token_masked = (
                "***************" if notifier.sudo().bot_token else "")

    @api.constrains("company_id", "active")
    def _check_one_active_per_company(self):
        """One company, one notification bot.

        Two active notifiers would each schedule their own job for the same
        message, and the operator would read everything twice. The search
        below sees only active records — ``active`` puts that in the default
        domain — so archiving one is how you replace it.
        """
        for notifier in self:
            if not notifier.active:
                continue
            # sudo(): this enforces a database invariant ("one active
            # notifier per company"), not an access boundary, so it must not
            # be scoped by rule_notifier_company. Without sudo() here, that
            # rule would make the search invisible to a twin in a company the
            # writing user does not currently carry, and the constraint would
            # silently let a duplicate through instead of refusing it.
            twin = self.sudo().search([
                ("id", "!=", notifier.id),
                ("company_id", "=", notifier.company_id.id),
            ], limit=1)
            if twin:
                raise ValidationError(_(
                    "%(company)s already notifies through %(name)s. One "
                    "company, one notification bot — archive that one first.",
                    company=notifier.company_id.display_name, name=twin.name))

    @api.model
    def _for_company(self, company):
        """The active notifier of ``company``, or an empty recordset.

        sudo: read from the job queue and from a public webhook request, both
        of which have no right to this model and no business having one.
        """
        return self.sudo().search([("company_id", "=", company.id)], limit=1)

    def _client(self):
        self.ensure_one()
        token = self.sudo().bot_token
        if not token:
            raise UserError(_("The notification bot token is not set."))
        return TelegramNotifyClient(
            token, self.api_base_url or "https://api.telegram.org")

    def _webhook_url(self):
        self.ensure_one()
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        return f"{base}/omnichannel/notify/telegram/{self.webhook_uuid}"

    def _set_error(self, description):
        self.sudo().write({"state": "error", "last_error": description})

    @api.model
    def _friendly(self, error):
        """An operator-facing sentence for a provider error."""
        description = (getattr(error, "description", "") or "").lower()
        for phrase, message in FRIENDLY_ERRORS.items():
            if phrase in description:
                return str(message)
        return _("Telegram error: %s",
                 getattr(error, "description", str(error)))

    @api.model
    def _notify_ui(self, message, kind="success"):
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": message, "type": kind,
                       "sticky": kind == "danger"},
        }

    def action_check_connection(self):
        """Ask Telegram who this token belongs to.

        ``check_access`` and not «the menu is behind the admin group»: a
        button is reachable through ``call_button`` on any model the caller
        can read, and operators hold read here.

        A provider failure is reported as a sticky danger notification, not
        a ``UserError``: the record has to come back carrying the failure —
        red state badge, ``last_error`` filled — and raising would roll that
        write away with the rest of the request, since Odoo only commits a
        request that returns successfully. The notification says the same
        thing to the admin and lets the write land.
        """
        self.ensure_one()
        self.check_access("write")
        try:
            me = self._client().get_me()
        except TelegramNotifyError as err:
            self._set_error(err.description)
            return self._notify_ui(self._friendly(err), kind="danger")
        self.sudo().write({
            "bot_username": me.get("username"),
            "bot_external_id": str(me.get("id")),
            "state": "connected",
            "last_error": False,
        })
        return self._notify_ui(_("Connected as @%s", me.get("username")))

    def action_register_webhook(self):
        """Point Telegram at this database and keep the secret it will send.

        An existing secret is reused: Telegram already holds it, and a fresh
        one would silently invalidate every update in flight.
        """
        self.ensure_one()
        self.check_access("write")
        secret = self.sudo().webhook_secret or uuid.uuid4().hex
        try:
            self._client().set_webhook(self._webhook_url(), secret)
        except TelegramNotifyError as err:
            self._set_error(err.description)
            return self._notify_ui(self._friendly(err), kind="danger")
        self.sudo().write({
            "webhook_secret": secret,
            "webhook_status": "registered",
            "state": "connected",
            "last_error": False,
        })
        return self._notify_ui(_("Webhook registered."))

    def action_remove_webhook(self):
        self.ensure_one()
        self.check_access("write")
        try:
            self._client().delete_webhook()
        except TelegramNotifyError as err:
            return self._notify_ui(self._friendly(err), kind="danger")
        self.sudo().write({"webhook_status": "removed"})
        return self._notify_ui(_("Webhook removed."))
