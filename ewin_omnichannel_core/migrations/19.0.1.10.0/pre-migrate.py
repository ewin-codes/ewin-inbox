from odoo.tools.sql import column_exists, rename_column


def migrate(cr, version):
    """Keep the names of the customers an Odoo 18 database already knows.

    On Odoo 18 an identity kept the name its channel reported in a stored
    ``display_name``. Odoo 19 owns that field on every model and computes it,
    so the name moved to ``name``. Renaming the column before the registry
    loads carries every stored name across; left alone, the new field would
    start empty and the old column would sit beside it unread.
    """
    table = "omnichannel_identity"
    if column_exists(cr, table, "display_name") and not column_exists(cr, table, "name"):
        rename_column(cr, table, "display_name", "name")
