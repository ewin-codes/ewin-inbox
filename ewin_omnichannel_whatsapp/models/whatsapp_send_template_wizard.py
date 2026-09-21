from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services.whatsapp_api_client import WhatsAppApiError


class WhatsAppSendTemplateWizard(models.TransientModel):
    _name = "omnichannel.whatsapp.send_template.wizard"
    _description = "Send WhatsApp Template"

    conversation_id = fields.Many2one(
        "omnichannel.conversation", required=True, ondelete="cascade")
    account_id = fields.Many2one(
        "omnichannel.account", related="conversation_id.account_id")
    template_id = fields.Many2one(
        "omnichannel.whatsapp.template", string="Template",
        domain="[('account_id','=',account_id),('active','=',True),"
               "('status','=','APPROVED')]")
    line_ids = fields.One2many(
        "omnichannel.whatsapp.send_template.wizard.line", "wizard_id",
        string="Variables")
    preview = fields.Text(compute="_compute_preview")

    @api.onchange("template_id")
    def _onchange_template_id(self):
        count = self.template_id.variables_count or 0
        self.line_ids = [(5, 0, 0)] + [
            (0, 0, {"sequence": n, "name": "{{%d}}" % n})
            for n in range(1, count + 1)
        ]

    @api.depends("template_id", "line_ids.value")
    def _compute_preview(self):
        for wizard in self:
            if not wizard.template_id:
                wizard.preview = ""
                continue
            text = wizard.template_id.body_preview or ""
            for line in wizard.line_ids:
                text = text.replace(line.name, line.value or line.name)
            wizard.preview = text

    def action_send(self):
        self.ensure_one()
        if not self.template_id:
            raise UserError(_("Select a template first."))
        values = [line.value or "" for line in self.line_ids.sorted("sequence")]
        connector = self.conversation_id.account_id._get_connector()
        try:
            connector.send_template(
                self.account_id, self.conversation_id, self.template_id,
                values)
        except WhatsAppApiError as err:
            # send_template logged the refusal against the account and the
            # conversation before re-raising. Report it by returning rather
            # than by letting the exception out: Odoo commits a request that
            # returns and rolls back one that does not, and that journal row
            # is the only record left that this customer was nearly messaged
            # - the message itself was never created.
            return connector._notify_ui(
                connector._friendly(err), kind="danger")
        return {"type": "ir.actions.act_window_close"}


class WhatsAppSendTemplateWizardLine(models.TransientModel):
    _name = "omnichannel.whatsapp.send_template.wizard.line"
    _description = "Send WhatsApp Template - Variable Line"

    wizard_id = fields.Many2one(
        "omnichannel.whatsapp.send_template.wizard", required=True,
        ondelete="cascade")
    sequence = fields.Integer(default=1)
    name = fields.Char(string="Placeholder", readonly=True)
    value = fields.Char(string="Value")
