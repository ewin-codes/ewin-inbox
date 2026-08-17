from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo import fields
from .common import OmnichannelCase


@tagged("post_install", "-at_install")
class TestJobQueue(OmnichannelCase):
    def setUp(self):
        super().setUp()
        self.account = self.env["omnichannel.account"].create(
            {"name": "Bot", "channel_id": self.channel.id})
        self.identity = self.env["omnichannel.identity"].create(
            {"account_id": self.account.id, "external_id": "1"})
        self.conv = self.env["omnichannel.conversation"].create({
            "name": "c", "account_id": self.account.id,
            "identity_id": self.identity.id})

    def _queued_message(self):
        return self.env["omnichannel.message"].create({
            "conversation_id": self.conv.id, "direction": "outbound",
            "sender_type": "operator", "message_type": "text",
            "body": "reply", "state": "queued"})

    def test_enqueue_and_process_runs_method(self):
        message = self._queued_message()
        job = self.env["omnichannel.job"].enqueue(
            model="omnichannel.routing.service", method="send_outbound",
            args={"message_id": message.id})
        self.assertEqual(job.state, "pending")
        with self._with_connector(self._fake_connector()):
            self.env["omnichannel.job"]._cron_process_jobs()
        self.assertEqual(job.state, "done")
        self.assertEqual(message.state, "sent")

    def test_failure_schedules_retry(self):
        message = self._queued_message()
        job = self.env["omnichannel.job"].enqueue(
            model="omnichannel.routing.service", method="send_outbound",
            args={"message_id": message.id})
        connector = self._fake_connector()
        connector.send_message.side_effect = ValueError("provider unreachable")
        with self._with_connector(connector):
            job.run()
        self.assertEqual(job.state, "pending")
        self.assertEqual(job.retry_count, 1)
        self.assertGreater(job.next_run_at, fields.Datetime.now())

    def test_run_refuses_a_target_that_did_not_opt_in(self):
        """The cron drains this queue as superuser, where neither access rights
        nor record rules apply. A row is therefore an instruction to the
        database owner, and only a method its own model published in
        ``_job_methods`` may be that instruction."""
        job = self.env["omnichannel.job"].create({
            "name": "escalation", "model": "res.users", "method": "create",
            "args": {"vals_list": [{"name": "Backdoor", "login": "backdoor"}]},
        })
        job.run()
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.retry_count, 0)  # terminal, never retried
        self.assertFalse(
            self.env["res.users"].search([("login", "=", "backdoor")]))

    def test_run_refuses_an_undeclared_method_on_a_declared_target(self):
        """Opting a model in publishes named methods, not the whole model."""
        job = self.env["omnichannel.job"].create({
            "name": "reach-in", "model": "omnichannel.routing.service",
            "method": "_download_attachments", "args": {},
        })
        job.run()
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.retry_count, 0)

    def test_run_refuses_an_unknown_model(self):
        job = self.env["omnichannel.job"].create({
            "name": "typo", "model": "no.such.model", "method": "run",
            "args": {},
        })
        job.run()
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.retry_count, 0)

    def test_omni_admin_cannot_write_the_queue(self):
        """The queue is machinery, not user data: every producer enqueues
        through sudo, so no group needs more than read on it."""
        admin = self.env["res.users"].create({
            "name": "Omni admin", "login": "omni_admin_job_test",
            "groups_id": [(4, self.env.ref(
                "ewin_omnichannel_core.group_omni_admin").id)]})
        with self.assertRaises(AccessError):
            self.env["omnichannel.job"].with_user(admin).create({
                "name": "escalation", "model": "res.users",
                "method": "create", "args": {}})
