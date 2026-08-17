import logging
import threading

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Retry backoff in seconds by attempt index (1st immediate).
RETRY_BACKOFF = [0, 60, 300, 1800, 7200]


class OmnichannelJob(models.Model):
    _name = "omnichannel.job"
    _description = "Omnichannel Job Queue"
    _order = "next_run_at, id"

    name = fields.Char()
    model = fields.Char(required=True)
    method = fields.Char(required=True)
    args = fields.Json(default=dict)
    state = fields.Selection(
        [("pending", "Pending"), ("running", "Running"),
         ("done", "Done"), ("failed", "Failed")],
        default="pending", required=True, index=True)
    next_run_at = fields.Datetime(default=fields.Datetime.now, index=True)
    retry_count = fields.Integer(default=0)
    max_retries = fields.Integer(default=5)
    last_error = fields.Text()
    company_id = fields.Many2one("res.company", index=True)

    @api.model
    def enqueue(self, model, method, args=None, company_id=None, delay_seconds=0):
        run_at = fields.Datetime.now()
        if delay_seconds:
            run_at = fields.Datetime.add(run_at, seconds=delay_seconds)
        return self.create({
            "name": f"{model}.{method}",
            "model": model,
            "method": method,
            "args": args or {},
            "company_id": company_id,
            "next_run_at": run_at,
        })

    def run(self):
        self.ensure_one()
        self.state = "running"
        try:
            target = self._resolve_target()
            getattr(target, self.method)(**(self.args or {}))
            self.state = "done"
        except NonRetriableError as err:
            self.write({"state": "failed", "last_error": str(err)})
        except Exception as err:  # noqa: BLE001
            self._schedule_retry(str(err))

    def _resolve_target(self):
        """Return the recordset this job may call — or refuse the job.

        ``_cron_process_jobs`` drains the queue as superuser, where neither
        access rights nor record rules apply, so a row is an instruction to
        the database owner. What a row may name is therefore not "any model"
        but a method its own model published in ``_job_methods``: the queue
        stays channel-agnostic (it never learns what a connector is) while the
        set of things it can be talked into doing stays enumerable by reading
        those declarations.

        A row naming anything else is a mistake or an attack, and either way
        will read the same on the next attempt — hence terminal, not retried.
        """
        target = self.env.get(self.model)
        if target is None:
            raise NonRetriableError(f"Unknown job target model {self.model!r}")
        if self.method not in getattr(target, "_job_methods", ()):
            raise NonRetriableError(
                f"{self.model}.{self.method} is not published to the job queue")
        return target

    def _schedule_retry(self, error):
        self.retry_count += 1
        if self.retry_count >= self.max_retries:
            self.write({"state": "failed", "last_error": error})
            target = self.env.get(self.model)
            if target is not None and hasattr(target, "_on_job_permanent_failure"):
                target._on_job_permanent_failure(self.method, self.args or {}, error)
            return
        idx = min(self.retry_count, len(RETRY_BACKOFF) - 1)
        delay = RETRY_BACKOFF[idx]
        self.write({
            "state": "pending",
            "last_error": error,
            "next_run_at": fields.Datetime.add(fields.Datetime.now(), seconds=delay),
        })

    @api.model
    def _cron_process_jobs(self, limit=50):
        now = fields.Datetime.now()
        jobs = self.search([
            ("state", "=", "pending"),
            ("next_run_at", "<=", now),
        ], limit=limit, order="next_run_at, id")
        for job in jobs:
            job.run()
            if not getattr(threading.current_thread(), "testing", False):
                # isolate each job; a failure must not roll back peers
                self.env.cr.commit()


class NonRetriableError(Exception):
    """Raise from a job target to mark the job failed without retry."""
