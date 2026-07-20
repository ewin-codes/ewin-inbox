import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class OmnichannelEvent(models.Model):
    _name = "omnichannel.event"
    _description = "Omnichannel Provider Event"
    _order = "id desc"

    account_id = fields.Many2one(
        "omnichannel.account", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(
        related="account_id.company_id", store=True, index=True)
    external_event_id = fields.Char(required=True, index=True)
    event_type = fields.Char()
    state = fields.Selection(
        [("pending", "Pending"), ("processed", "Processed"),
         ("failed", "Failed"), ("skipped", "Skipped")],
        default="pending", required=True, index=True)
    payload = fields.Json(
        groups="ewin_omnichannel_core.group_omni_admin", default=dict)
    received_at = fields.Datetime(default=fields.Datetime.now)
    processed_at = fields.Datetime()
    error = fields.Text()

    _sql_constraints = [
        ("account_event_uniq", "unique(account_id, external_event_id)",
         "Event already recorded for this account."),
    ]

    @api.model
    def record(self, account, external_event_id, event_type=False, payload=None):
        """Idempotently record an event. Returns (event, created)."""
        existing = self.search([
            ("account_id", "=", account.id),
            ("external_event_id", "=", external_event_id),
        ], limit=1)
        if existing:
            return existing, False
        try:
            with self.env.cr.savepoint():
                event = self.create({
                    "account_id": account.id,
                    "external_event_id": external_event_id,
                    "event_type": event_type,
                    "payload": payload or {},
                })
            return event, True
        except Exception:  # unique violation from a concurrent duplicate
            existing = self.search([
                ("account_id", "=", account.id),
                ("external_event_id", "=", external_event_id),
            ], limit=1)
            return existing, False

    def mark_processed(self):
        self.write({"state": "processed", "processed_at": fields.Datetime.now()})

    def mark_failed(self, error):
        self.write({"state": "failed", "error": error})

    @api.model
    def _cron_cleanup(self, days=30):
        from datetime import timedelta
        cutoff = fields.Datetime.now() - timedelta(days=days)
        self.search([("state", "in", ("processed", "skipped")),
                     ("received_at", "<", cutoff)]).unlink()
        self.env["omnichannel.job"].search([
            ("state", "in", ("done", "failed")),
            ("write_date", "<", cutoff)]).unlink()
        self.env["omnichannel.error.log"].search([
            ("state", "=", "resolved"),
            ("create_date", "<", cutoff)]).unlink()
