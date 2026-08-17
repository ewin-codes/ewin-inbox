from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Restrict mirror channels that were created open to every employee.

    ``_ensure_discuss_channel`` used to leave ``group_public_id`` to mail's
    compute, which stamps ``base.group_user`` on a parent-less channel — and
    the read rule that grants access by that group is what made every mirror,
    internal notes included, readable company-wide. New channels now carry the
    operator group; the ones already in the database have to be moved by hand,
    because a fix that only applies going forward leaves the whole existing
    history exposed.

    Channels a human deliberately re-scoped to some other group are left
    alone: only the computed default is corrected.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    operator_group = env.ref(
        "ewin_omnichannel_core.group_omni_operator", raise_if_not_found=False)
    employees = env.ref("base.group_user", raise_if_not_found=False)
    if not operator_group or not employees:
        return
    mirrors = env["discuss.channel"].search([
        ("omni_conversation_id", "!=", False),
        ("group_public_id", "=", employees.id),
    ])
    if mirrors:
        mirrors.write({"group_public_id": operator_group.id})
