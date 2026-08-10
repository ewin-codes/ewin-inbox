from odoo import api, models


class RoutingService(models.AbstractModel):
    _name = "omnichannel.routing.service"
    _description = "Omnichannel Routing Service"

    @api.model
    def process_event(self, account, normalized_event):
        """Run the inbound flow from a universal normalized event."""
        external_user = normalized_event["external_user"]
        identity = self.env["omnichannel.identity.service"].find_or_create(
            account, external_user)
        auto_create = account.connector_config.get("create_contacts", True) \
            if isinstance(account.connector_config, dict) else True
        self.env["omnichannel.identity.service"].ensure_partner(identity, auto_create)
        conversation = self.env["omnichannel.conversation.service"].find_or_create(
            account, identity,
            thread_external_ids=normalized_event.get("thread_reference"))
        if not conversation.partner_id and identity.partner_id:
            conversation.partner_id = identity.partner_id
        normalized_message = dict(normalized_event["message"])
        normalized_message["external_message_id"] = normalized_event.get(
            "external_message_id")
        attachments = self._download_attachments(account, normalized_message)
        message = self.env["omnichannel.message.service"].create_inbound(
            conversation, normalized_message, attachments)
        return message

    @api.model
    def _download_attachments(self, account, normalized_message):
        """Ask the connector to download provider attachments to ir.attachment."""
        result = self.env["ir.attachment"]
        specs = normalized_message.get("attachments") or []
        if not specs:
            return result
        connector = account._get_connector()
        for spec in specs:
            try:
                att = connector.download_attachment(account, spec)
                if att:
                    result |= att
            except NotImplementedError:
                pass
        return result

    @api.model
    def enqueue_outbound(self, message):
        """Enqueue outbound send via the job queue (used for retries)."""
        self.env["omnichannel.job"].enqueue(
            model="omnichannel.routing.service",
            method="send_outbound",
            args={"message_id": message.id},
            company_id=message.company_id.id,
        )

    @api.model
    def deliver_outbound(self, message):
        """Attempt the first send synchronously.

        Runs in the operator's request so the reply is delivered without
        waiting for the cron. A retriable failure is handed off to the retry
        queue; a terminal failure marks the message failed. Never raises to
        the caller (that would roll back the just-created message)."""
        from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
            import NonRetriableError
        account = message.account_id
        connector = account._get_connector()
        try:
            connector.send_message(account, message)
        except NonRetriableError:
            message.write({"state": "failed"})
            message.conversation_id._notify_omni_event("message_failed")
        except Exception:  # noqa: BLE001 - transient: retry via the queue
            message.write({"state": "queued"})
            self.enqueue_outbound(message)

    @api.model
    def send_outbound(self, message_id):
        message = self.env["omnichannel.message"].browse(message_id).exists()
        if not message:
            return
        from odoo.addons.ewin_omnichannel_core.models.omnichannel_job \
            import NonRetriableError
        account = message.account_id
        connector = account._get_connector()
        try:
            connector.send_message(account, message)
        except NonRetriableError:
            # terminal: mark the message failed, notify, do not retry
            message.write({"state": "failed"})
            message.conversation_id._notify_omni_event("message_failed")
            raise
        except Exception:
            # retriable transient error: leave the message queued for the queue
            # to retry. error_message was already recorded by the connector
            # for visibility.
            message.write({"state": "queued"})
            raise

    @api.model
    def _on_job_permanent_failure(self, method, args, error):
        """Hook invoked by omnichannel.job when retries are exhausted.

        Keeps the job queue channel-agnostic: it only knows to call this
        hook if the target model defines it, not that it deals with
        messages at all.
        """
        if method != "send_outbound":
            return
        message = self.env["omnichannel.message"].browse(args.get("message_id")).exists()
        if not message:
            return
        message.write({"state": "failed"})
        message.conversation_id._notify_omni_event("message_failed")
