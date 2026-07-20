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
            target = self.env[self.model]
            getattr(target, self.method)(**(self.args or {}))
            self.state = "done"
        except NonRetriableError as err:
            self.write({"state": "failed", "last_error": str(err)})
        except Exception as err:  # noqa: BLE001
            self._schedule_retry(str(err))

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
