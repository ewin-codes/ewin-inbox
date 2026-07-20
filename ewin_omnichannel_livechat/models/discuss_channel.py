import logging

from odoo import models

_logger = logging.getLogger(__name__)


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
        try:
            omni_message = self.env["omnichannel.routing.service"].sudo(
                ).process_event(account, normalized)
            conversation = omni_message.conversation_id
            if conversation and conversation.livechat_channel_id != self:
                conversation.sudo().livechat_channel_id = self.id
            event.mark_processed()
        except Exception as err:  # noqa: BLE001
            event.mark_failed(str(err))
            self.env["omnichannel.error.log"].sudo().log(
                "internal", "Failed to ingest livechat message",
                account=account, event_id=event.id, technical=str(err))
            raise
