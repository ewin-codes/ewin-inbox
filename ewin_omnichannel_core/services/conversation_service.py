from odoo import api, fields, models


class ConversationService(models.AbstractModel):
    _name = "omnichannel.conversation.service"
    _description = "Omnichannel Conversation Service"

    @api.model
    def find_or_create(self, account, identity, reopen_closed=True,
                       thread_external_ids=None):
        Conversation = self.env["omnichannel.conversation"]
        if thread_external_ids:
            threaded = self.env["omnichannel.message"].search([
                ("account_id", "=", account.id),
                ("external_message_id", "in", list(thread_external_ids)),
            ], limit=1, order="id desc")
            if threaded:
                conv = threaded.conversation_id
                if conv.state == "closed" and reopen_closed:
                    conv.action_reopen()
                return conv
        conv = Conversation.search([
            ("account_id", "=", account.id),
            ("identity_id", "=", identity.id),
            ("state", "!=", "closed"),
        ], limit=1)
        if conv:
            return conv
        if reopen_closed:
            closed = Conversation.search([
                ("account_id", "=", account.id),
                ("identity_id", "=", identity.id),
                ("state", "=", "closed"),
            ], limit=1, order="id desc")
            if closed:
                closed.action_reopen()
                return closed
        partner = identity.partner_id
        conv = Conversation.create({
            "name": partner.name if partner else (identity.display_name or "Conversation"),
            "account_id": account.id,
            "identity_id": identity.id,
            "partner_id": partner.id if partner else False,
            "operator_id": account.default_user_id.id or False,
            "team_id": account.default_team_id.id or False,
            "state": "open" if account.default_user_id else "new",
        })
        conv._notify_omni_event("conversation_created")
        return conv
