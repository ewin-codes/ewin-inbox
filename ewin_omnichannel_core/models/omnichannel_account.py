import uuid

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OmnichannelAccount(models.Model):
    _name = "omnichannel.account"
    _description = "Omnichannel Channel Account"
    _order = "sequence, name"

    name = fields.Char(required=True)
    channel_id = fields.Many2one(
        "omnichannel.channel", required=True, ondelete="restrict", index=True
    )
    channel_code = fields.Char(related="channel_id.code", store=True, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    active = fields.Boolean(default=True)
    state = fields.Selection(
        [("draft", "Draft"), ("connected", "Connected"),
         ("error", "Error"), ("disabled", "Disabled")],
        default="draft", required=True, index=True,
    )
    default_team_id = fields.Many2one("omnichannel.team")
    default_user_id = fields.Many2one("res.users", string="Default Operator")
    webhook_uuid = fields.Char(
        required=True, copy=False, index=True,
        default=lambda self: uuid.uuid4().hex,
    )
    last_webhook_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)
    connector_config = fields.Json(default=dict)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        ("webhook_uuid_uniq", "unique(webhook_uuid)", "Webhook UUID must be unique."),
    ]

    def _get_connector(self):
        """Return the connector model for this account's channel code."""
        self.ensure_one()
        code = self.channel_id.code
        model_name = f"omnichannel.connector.{code}"
        if model_name not in self.env:
            raise UserError(
                _("No connector installed for channel '%s'.", code)
            )
        return self.env[model_name]

    def _get_public_address(self):
        """The address the customer writes to: a mailbox, a @bot, a phone
        number, a page.

        Only the connector knows which of its fields that is, so each one
        overrides this for its own channel code and defers to ``super()`` for
        the rest. An empty string when nobody knows — never ``False`` and
        never a bare ``@``, so a caller can fall back with a plain ``or``.

        Overrides read their field under ``sudo()``. The Telegram notifier
        asks from the job queue's cron, and whoever asks next must not trip
        over a field some connector put behind a group.
        """
        self.ensure_one()
        return ""

    def _run_connector_action(self, method, **kwargs):
        """Run a connector maintenance action on this account.

        These are the form's buttons: connect, register or remove a webhook,
        refresh a token, sync templates. Every one of them administers the
        account, and every one is implemented inside the connector with
        ``sudo()`` because the credentials it touches are admin-only fields.
        The buttons living behind an admin-only menu is presentation, not a
        control — ``call_button`` reaches any public method on a model the
        caller can read, and operators hold read here. So the right to do it
        is asked once, in the single doorway they all pass through.
        """
        self.ensure_one()
        self.check_access("write")
        return getattr(self._get_connector(), method)(self, **kwargs)

    def action_disable(self):
        self.write({"state": "disabled", "active": False})

    def _set_error(self, message):
        self.write({"state": "error", "last_error": message})

    def _write_isolated(self, vals):
        """Write ``vals`` on this account in its own, immediately committed
        transaction.

        Some providers validate a webhook by calling it back *while* the
        registering request is still running (Viber does). The callback is a
        separate request: it commits its own write to this very row, so the
        write the registering transaction makes afterwards fails with
        ``could not serialize access due to concurrent update``. Odoo then
        retries the whole request, the retry calls the provider again, the
        provider calls back again — the conflict repeats until the retries run
        out and the registration result is lost, even though the provider
        accepted it. Writing through a short-lived cursor keeps the two
        transactions from overlapping.

        The caller must not have written this row earlier in the ongoing
        transaction: the isolated cursor would then block on the row lock that
        transaction still holds.
        """
        self.ensure_one()
        with self.pool.cursor() as cr:
            account = self.with_env(self.env(cr=cr))
            account.write(vals)
            # Flush explicitly: a transaction only tracks its environments
            # weakly, so an environment left to garbage collection takes the
            # pending write with it and the commit stores nothing.
            account.env.flush_all()
        self.invalidate_recordset(list(vals))
