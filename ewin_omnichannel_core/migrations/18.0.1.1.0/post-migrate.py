from odoo import SUPERUSER_ID, api

from odoo.addons.ewin_omnichannel_core.hooks import backfill_existing_history


def migrate(cr, version):
    """Catch up the history on a database that already had this module.

    ``post_init_hook`` fires on install only, so an installation that has been
    running EWIN Inbox since before the customer history existed would never
    see its own past mirrored. Same function, the other door.
    """
    backfill_existing_history(api.Environment(cr, SUPERUSER_ID, {}))
