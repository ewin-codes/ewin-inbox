from odoo import models


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def message_post(self, *, message_type="notification", **kwargs):
        message = super().message_post(message_type=message_type, **kwargs)
        self._omni_livechat_ingest(message)
        return message

    def _omni_livechat_ingest(self, message):
        """Ingest a visitor message posted in a bridged livechat session (L).

        Runs sudo and synchronously in the visitor's request, mirroring the
        synchronous shape of the webhook connectors. Our own outbound posts
        carry ``omni_livechat_outbound`` and are ignored to avoid a loop."""
        if self.env.context.get("omni_livechat_outbound"):
            return
        if self.channel_type != "livechat":
            return
        normalizer = self.env["omnichannel.livechat.normalizer"]
        if not normalizer.is_visitor_message(self, message):
            return
        account = self.env["omnichannel.account"]._livechat_find_for_channel(
            self.livechat_channel_id)
        if not account:
            return
        normalized = normalizer.normalize_message(account, self, message)
        if normalized is None:
            return
        event, created = self.env["omnichannel.event"].sudo().record(
            account, normalizer.event_id_for(message), "message",
            normalized["raw_payload"])
        if not created and event.state in ("processed", "skipped"):
            return
        # This runs synchronously inside the visitor's own message_post
        # request (there is no controller wrapping this, unlike the webhook
        # connectors). An uncaught exception here would roll back the whole
        # request transaction, undoing super().message_post() and erasing the
        # visitor's message from the live session - and it would also wipe
        # out the failure bookkeeping below. So ingest side-effects are
        # confined to a savepoint: on failure only those writes unwind, the
        # visitor's message and the failure record survive in the outer
        # transaction, and nothing is re-raised into the visitor's request.
        try:
            with self.env.cr.savepoint():
                omni_message = self.env["omnichannel.routing.service"].sudo(
                    ).process_event(account, normalized)
                conversation = omni_message.conversation_id
                if conversation and conversation.livechat_channel_id != self:
                    conversation.sudo().livechat_channel_id = self.id
        except Exception as err:  # noqa: BLE001
            event.mark_failed(str(err))
            self.env["omnichannel.error.log"].sudo().log(
                "internal", "Failed to ingest livechat message",
                account=account, event_id=event.id, technical=str(err))
            return
        event.mark_processed()

    def _close_livechat_session(self, **kwargs):
        res = super()._close_livechat_session(**kwargs)
        Conversation = self.env["omnichannel.conversation"].sudo()
        for channel in self.filtered(
                lambda c: c.channel_type == "livechat"):
            conv = Conversation.search([
                ("livechat_channel_id", "=", channel.id),
                ("state", "not in", ("closed", "pending")),
            ], limit=1)
            if conv:
                conv.action_set_pending()
        return res
