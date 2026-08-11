from odoo import SUPERUSER_ID, api

from odoo.addons.ewin_omnichannel_core.hooks import backfill_existing_history


def migrate(cr, version):
    """Catch up the lead history that core's own migration cannot reach.

    Odoo loads and migrates one module at a time, in dependency order, and a
    module's own post-migrate runs right after its own models are registered
    — see ``load_module_graph`` in ``odoo/modules/loading.py``. Core's post
    hook therefore always runs *before* this module extends
    ``_history_targets`` with ``lead_id``, so it only ever sees the contact.
    By the time this migration runs, the override is in force and a
    conversation's lead is a target too.

    Idempotent for the same reason core's is: ``backfill`` skips a message
    that already has a copy on a given target, so re-walking conversations
    core already handled costs a no-op lookup, not a duplicate note.
    """
    backfill_existing_history(api.Environment(cr, SUPERUSER_ID, {}))
