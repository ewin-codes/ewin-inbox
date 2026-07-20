from odoo import fields, models


class OmnichannelChannel(models.Model):
    _name = "omnichannel.channel"
    _description = "Omnichannel Channel Type"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(
        required=True,
        help="Unique channel code, e.g. 'telegram', 'whatsapp'.",
    )
    active = fields.Boolean(default=True)
    connector_module = fields.Char(help="Technical name of the connector module.")
    icon = fields.Binary(attachment=True)
    capabilities = fields.Json(
        default=dict,
        help="Supported capabilities, e.g. {'text': true, 'image': true}.",
    )

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Channel code must be unique."),
    ]
