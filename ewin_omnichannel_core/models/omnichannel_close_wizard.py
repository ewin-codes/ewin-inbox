from odoo import _, fields, models
from odoo.exceptions import UserError


class OmnichannelCloseWizard(models.TransientModel):
    _name = "omnichannel.close.wizard"
    _description = "Close Conversation"

    conversation_ids = fields.Many2many(
        "omnichannel.conversation", "omni_close_wizard_conv_rel",
        "wizard_id", "conversation_id", string="Conversations", required=True)
    reason_id = fields.Many2one(
        "omnichannel.close.reason", string="Reason",
        domain="[('active', '=', True)]")
    note = fields.Text(
        string="Comment",
        help="Anything the preset reasons do not cover.")
    policy = fields.Selection(
        [("optional", "Optional"), ("required", "Required")],
        compute="_compute_policy",
        help="Mirrors the Closing setting so the form can say whether an "
             "answer is mandatory.")

    def _compute_policy(self):
        # "off" never reaches the wizard — action_close closes directly then —
        # so anything that is not "required" is presented as optional.
        policy = self.env["omnichannel.conversation"]._close_reason_policy()
        for wizard in self:
            wizard.policy = "required" if policy == "required" else "optional"

    def action_confirm(self):
        """Close the conversations, refusing an empty answer when the setting
        makes one mandatory.

        The check lives here and not in the view: a ``required`` attribute in
        the arch is a client-side courtesy that an RPC call skips, and the
        point of the policy is that the Closed state is never written without
        an answer. Raising before ``_close`` leaves the conversations exactly
        as they were.
        """
        self.ensure_one()
        note = (self.note or "").strip()
        if self.policy == "required" and not self.reason_id and not note:
            raise UserError(_(
                "Pick a reason or write a comment to close this "
                "conversation."))
        self.conversation_ids._close(reason=self.reason_id, note=note)
        return {"type": "ir.actions.act_window_close"}
