from odoo.tests import tagged
from odoo import fields
from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestJobQueue(OmnichannelCase):
    def test_enqueue_and_process_runs_method(self):
        # Use error-log as a side-effect target
        job = self.env["omnichannel.job"].enqueue(
            model="omnichannel.error.log", method="log",
            args={"category": "internal", "summary": "from job"})
        self.assertEqual(job.state, "pending")
        self.env["omnichannel.job"]._cron_process_jobs()
        self.assertEqual(job.state, "done")
        self.assertTrue(self.env["omnichannel.error.log"].search(
            [("summary", "=", "from job")]))

    def test_failure_schedules_retry(self):
        job = self.env["omnichannel.job"].enqueue(
            model="omnichannel.error.log", method="nonexistent_method", args={})
        job.run()
        self.assertEqual(job.state, "pending")
        self.assertEqual(job.retry_count, 1)
        self.assertGreater(job.next_run_at, fields.Datetime.now())
